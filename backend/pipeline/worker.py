import hashlib, json, shutil, threading, time
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from ..database.store import connect
from ..detection.models import ModelHub
from ..consensus.engine import match_and_score
from ..core.config import CLASSES, IMAGE_EXTS, DATA_ROOT
from ..traffic.analysis import analyze_all as analyze_traffic

class JobRunner:
    def __init__(self):
        self.hub = ModelHub()
        self.thread = None
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def start(self, config, resume=False):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise RuntimeError('Đang có job chạy.')
            self.pause_event.clear()
            self.stop_event.clear()
            if resume:
                with connect() as db:
                    row = db.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 1').fetchone()
                    if not row: raise RuntimeError('Không có job để tiếp tục.')
                    job_id = row['id']
                    if not config: config = json.loads(row['config'])
                    db.execute("UPDATE images SET status='pending',error=NULL WHERE status IN ('failed','processing')")
                    total = db.execute("SELECT count(*) FROM images WHERE status!='processed'").fetchone()[0]
                    db.execute("UPDATE jobs SET state='running',total=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (total, job_id))
            else:
                with connect() as db:
                    total = db.execute("SELECT count(*) FROM images WHERE status!='processed'").fetchone()[0]
                    if not total: raise RuntimeError('Hãy nhập thư mục ảnh trước.')
                    db.execute("INSERT INTO jobs(state,config,total) VALUES('running',?,?)", (json.dumps(config), total))
                    job_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            self.thread = threading.Thread(target=self._run, args=(job_id, config), daemon=True, name='autolabel-job')
            self.thread.start()
            return job_id

    def pause(self):
        self.pause_event.set()
        with connect() as db:
            db.execute("UPDATE jobs SET state='paused',updated_at=CURRENT_TIMESTAMP WHERE state='running'")

    def resume(self):
        self.pause_event.clear()
        if not self.thread or not self.thread.is_alive():
            return self.start({}, resume=True)
        with connect() as db:
            db.execute("UPDATE jobs SET state='running',updated_at=CURRENT_TIMESTAMP WHERE state='paused'")
        return None

    def stop(self):
        self.stop_event.set()
        self.pause_event.clear()
        with connect() as db:
            db.execute("UPDATE jobs SET state='stopped',current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE state IN ('running','paused')")
            db.execute("UPDATE images SET status='pending',error=NULL WHERE status='processing'")

    def cancel(self):
        self.stop_event.set()
        self.pause_event.clear()
        with connect() as db:
            db.execute("UPDATE jobs SET state='cancelled',current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE state IN ('running','paused')")
            db.execute("UPDATE images SET status='pending',error=NULL WHERE status='processing'")

    def _run(self, job_id, config):
        try:
            y = self.hub.load_yolo(config['yolo_model'], config.get('device', 'auto'))
            # New jobs must never retain an optional model from an earlier job.
            self.hub.dino=self.hub.dino_processor=self.hub.dino_path=None
            self.hub.sam=self.hub.sam_processor=self.hub.sam_path=None
            if config.get('dino_model'): self.hub.load_dino(config['dino_model'])
            if config.get('sam_model'): self.hub.load_sam(config['sam_model'])
            DATA_ROOT.mkdir(exist_ok=True, parents=True)

            out_path = config.get('output_dir')
            auto_save_active = bool(out_path and str(out_path).strip())
            if auto_save_active:
                out_dir = Path(out_path.strip()).expanduser().resolve()
                out_images = out_dir / 'images'
                out_labels = out_dir / 'labels'
                out_images.mkdir(parents=True, exist_ok=True)
                out_labels.mkdir(parents=True, exist_ok=True)
                data_yaml = out_dir / 'data.yaml'
                if not data_yaml.exists():
                    yaml_content = "path: .\ntrain: images\nval: images\nnames:\n" + "".join(f"  {i}: {name}\n" for i, name in enumerate(CLASSES))
                    data_yaml.write_text(yaml_content)
                classes_txt = out_dir / 'classes.txt'
                if not classes_txt.exists():
                    classes_txt.write_text('\n'.join(CLASSES) + '\n')

            with connect() as db:
                rows = db.execute("SELECT * FROM images WHERE status!='processed' ORDER BY id").fetchall()
                job_init = db.execute("SELECT processed, failed FROM jobs WHERE id=?", (job_id,)).fetchone()
                processed_count = job_init['processed'] if job_init else 0
                failed_count = job_init['failed'] if job_init else 0

            for row in rows:
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    with connect() as db:
                        db.execute("UPDATE jobs SET state='paused',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
                    time.sleep(0.3)
                if self.stop_event.is_set():
                    break

                with connect() as db:
                    db.execute("UPDATE jobs SET state='running',current_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['rel_path'], job_id))
                    db.execute("UPDATE images SET status='processing',error=NULL WHERE id=?", (row['id'],))

                t0 = time.time()
                try:
                    with Image.open(row['path']) as im: image = im.convert('RGB')
                    yd = self.hub.yolo_predict(image, config.get('yolo_conf', 0.25), config.get('imgsz', 960), config.get('mode', 'standard'))
                    dino_error = None
                    try:
                        dd = self.hub.dino_predict(image, config.get('dino_box_threshold', 0.28), config.get('dino_text_threshold', 0.25)) if self.hub.dino else []
                    except Exception as e:
                        dd = []
                        dino_error = str(e)[:400]
                    final = match_and_score(yd, dd, *image.size, config.get('match_iou', 0.4))
                    if dino_error:
                        for d in final: d['metadata']['dino_error'] = dino_error
                    for d in final:
                        if d['source'] == 'yolo_only' and not self.hub.dino:
                            d['quality'] = 'needs_review'
                            d['accepted'] = False
                        if d['quality'] == 'high_agreement' and config.get('auto_accept', False):
                            d['accepted'] = True
                        if (d['source'] == 'yolo_only' and not self.hub.dino
                                and config.get('accept_yolo_only', False)
                                and d['class_name'] in CLASSES):
                            d['accepted'] = True
                            d['metadata']['acceptance_policy'] = 'unverified_yolo_only_opt_in'
                        d['image_id'] = row['id']

                    sam_error = None
                    if self.hub.sam and final:
                        try: self.hub.sam_refine(image, final, DATA_ROOT / 'masks')
                        except Exception as e:
                            sam_error = str(e)[:400]
                            for d in final: d['metadata']['sam_error'] = sam_error

                    processed_count += 1
                    with connect() as db:
                        db.execute("DELETE FROM annotations WHERE image_id=? AND source NOT IN ('original','manual') AND reviewed=0", (row['id'],))
                        for d in final:
                            if d['class_name'] not in (*CLASSES, 'ambiguous'): continue
                            b = d['box']
                            class_id = CLASSES.index(d['class_name']) if d['class_name'] in CLASSES else -1
                            db.execute("INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,score,quality,heuristic_score,accepted,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (row['id'], d['source'], d['class_name'], class_id, *b, d['score'], d['quality'], d['heuristic_score'], int(d['accepted']), json.dumps(d['metadata'], ensure_ascii=False)))
                        db.execute("UPDATE images SET status='processed',processed_at=CURRENT_TIMESTAMP,error=NULL WHERE id=?", (row['id'],))
                        db.execute("UPDATE jobs SET processed=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (processed_count, job_id))
                        db.execute("INSERT INTO events(image_id,level,message) VALUES(?,?,?)", (row['id'], 'info', f"Đã xử lý trong {time.time()-t0:.2f}s; YOLO={len(yd)}, DINO={len(dd)}"))
                        if dino_error or sam_error:
                            db.execute("INSERT INTO events(image_id,level,message) VALUES(?,?,?)", (row['id'], 'warning', 'DINO: ' + str(dino_error) + '; SAM: ' + str(sam_error)))

                    # Incremental real-time file save (gán tới đâu lưu tới đó)
                    if auto_save_active:
                        try:
                            src_img = Path(row['path'])
                            dst_img = out_images / f"{row['id']:08d}_{src_img.name}"
                            if not dst_img.exists():
                                shutil.copy2(src_img, dst_img)
                            w, he = image.size
                            lines = []
                            for d in final:
                                cname = d.get('class_name')
                                if cname in CLASSES and d.get('accepted'):
                                    cid = CLASSES.index(cname)
                                    b = d['box']
                                    bw = (b[2] - b[0]) / w
                                    bh = (b[3] - b[1]) / he
                                    cx = (b[0] + b[2]) / (2 * w)
                                    cy = (b[1] + b[3]) / (2 * he)
                                    if bw > 0 and bh > 0:
                                        lines.append(f"{cid} {cx:.7f} {cy:.7f} {bw:.7f} {bh:.7f}")
                            dst_lbl = out_labels / f"{row['id']:08d}_{src_img.stem}.txt"
                            dst_lbl.write_text('\n'.join(lines) + ('\n' if lines else ''))
                        except Exception as e:
                            with connect() as db:
                                db.execute("INSERT INTO events(image_id,level,message) VALUES(?,?,?)", (row['id'], 'warning', f"Lỗi auto-save {out_dir}: {str(e)[:300]}"))

                except Exception as e:
                    failed_count += 1
                    with connect() as db:
                        db.execute("UPDATE images SET status='failed',error=? WHERE id=?", (str(e)[:1000], row['id']))
                        db.execute("UPDATE jobs SET failed=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (failed_count, job_id))
                        db.execute("INSERT INTO events(image_id,level,message) VALUES(?,?,?)", (row['id'], 'error', str(e)[:1000]))

            if not self.stop_event.is_set() and not self.pause_event.is_set():
                try:
                    summary = analyze_traffic()
                    with connect() as db:
                        db.execute("INSERT INTO events(level,message) VALUES(?,?)", ('info', f"Traffic feature pass: {summary['processed']} ảnh, {summary['labeled']} pseudo-label, {summary['needs_review']} cần review"))
                except Exception as e:
                    with connect() as db:
                        db.execute("INSERT INTO events(level,message) VALUES(?,?)", ('warning', f"Traffic analysis sau detection lỗi: {str(e)[:500]}"))

            with connect() as db:
                state = 'cancelled' if self.stop_event.is_set() else ('paused' if self.pause_event.is_set() else 'completed')
                db.execute("UPDATE jobs SET state=?,current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, job_id))

        except Exception as e:
            with connect() as db:
                db.execute("UPDATE jobs SET state=?,error=?,current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", ('failed', str(e)[:1000], job_id))
