import hashlib, json, shutil, time, re
from datetime import datetime
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from ..core.config import IMAGE_EXTS, CLASSES, DATA_ROOT
from ..database.store import connect

def clear_dataset():
    with connect() as db:
        db.execute('DELETE FROM annotations')
        db.execute('DELETE FROM traffic_measurements')
        db.execute('DELETE FROM annotation_history')
        db.execute('DELETE FROM events')
        db.execute('DELETE FROM images')
        db.execute("UPDATE jobs SET state='cancelled',current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE state IN ('running','paused')")
        masks_dir = DATA_ROOT / 'masks'
        if masks_dir.exists():
            for f in masks_dir.glob('*.png'):
                try: f.unlink()
                except Exception: pass
    return {'cleared': True, 'message': 'Đã làm mới project, sẵn sàng nhập thư mục mới.'}

def import_folder(folder, clear_first=False):
    if clear_first:
        clear_dataset()
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Đường dẫn dataset không phải thư mục tồn tại.')
    
    # Fast scan of all image files
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    
    added = 0
    duplicates = 0
    broken = 0
    
    with connect() as db:
        # Pre-load existing hashes and paths for O(1) in-memory lookup
        existing_hashes = set(r[0] for r in db.execute('SELECT sha256 FROM images').fetchall())
        existing_paths = set(r[0] for r in db.execute('SELECT path FROM images').fetchall())
        
        for path in files:
            try:
                # 1. Skip 0-byte or corrupted empty files immediately (0.001ms)
                st = path.stat()
                if st.st_size == 0:
                    broken += 1
                    continue
                
                str_path = str(path)
                if str_path in existing_paths:
                    duplicates += 1
                    continue
                
                # 2. SHA-256 hash calculation
                h = hashlib.sha256()
                with path.open('rb') as f:
                    for chunk in iter(lambda: f.read(1024*1024), b''):
                        h.update(chunk)
                digest = h.hexdigest()
                
                if digest in existing_hashes:
                    duplicates += 1
                    continue
                
                # 3. Fast image dimension reading (reads header only)
                with Image.open(path) as im:
                    w, he = im.size
                
                rel = str(path.relative_to(root))
                camera = Path(rel).parts[0] if len(Path(rel).parts) > 1 else 'default'
                stamp = None
                m = re.search(r'(?<!\d)(\d{4})(\d{2})(\d{2})[_T-](\d{2})(\d{2})(\d{2})(?!\d)', path.stem)
                if m:
                    try:
                        stamp = datetime.strptime(''.join(m.groups()), '%Y%m%d%H%M%S').isoformat(sep=' ')
                    except ValueError:
                        pass
                
                existing_hashes.add(digest)
                existing_paths.add(str_path)
                
                cur = db.execute(
                    'INSERT INTO images(path,rel_path,sha256,width,height,camera_id,timestamp) VALUES(?,?,?,?,?,?,?)',
                    (str_path, rel, digest, w, he, camera, stamp)
                )
                iid = cur.lastrowid
                added += 1
                
                # Check for existing label txt files
                if path.parent.name == 'images':
                    label_candidates = [
                        path.parent.parent / 'labels' / path.with_suffix('.txt').name,
                        path.parent.parent / 'labels' / path.parent.name / path.with_suffix('.txt').name
                    ]
                else:
                    label_candidates = [path.parent / 'labels' / path.with_suffix('.txt').name]
                label_candidates.append(path.with_suffix('.txt'))
                
                label = next((p for p in label_candidates if p.is_file()), None)
                if label:
                    for line_no, line in enumerate(label.read_text(errors='replace').splitlines(), 1):
                        try:
                            parts = line.split()
                            cls = int(parts[0])
                            vals = list(map(float, parts[1:5]))
                            if cls not in range(len(CLASSES)) or len(vals) != 4 or not all(0 <= v <= 1 for v in vals):
                                raise ValueError('invalid YOLO row')
                            cx, cy, bw, bh = vals
                            box = [max(0, (cx - bw/2) * w), max(0, (cy - bh/2) * he), min(w, (cx + bw/2) * w), min(he, (cy + bh/2) * he)]
                            db.execute(
                                'INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,quality,accepted,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (iid, 'original', CLASSES[cls], cls, *box, 'imported', 1, json.dumps({'label_file': str(label), 'line': line_no}))
                            )
                        except Exception as e:
                            db.execute('INSERT INTO events(image_id,level,message) VALUES(?,?,?)', (iid, 'warning', f'Lỗi nhãn {label}:{line_no}: {e}'))
                            
            except (UnidentifiedImageError, OSError, ValueError) as e:
                broken += 1
                db.execute('INSERT INTO events(level,message) VALUES(?,?)', ('warning', f'Ảnh lỗi/không đọc được {path}: {e}'[:1000]))
                
    return {'added': added, 'duplicates': duplicates, 'broken': broken, 'scanned': len(files)}

def export_dataset(name='export', output_dir=None):
    rows = []
    with connect() as db:
        imgs = db.execute("SELECT * FROM images ORDER BY id").fetchall()
        for im in imgs:
            anns = db.execute('SELECT * FROM annotations WHERE image_id=? AND accepted=1 ORDER BY id', (im['id'],)).fetchall()
            if anns:
                rows.append((dict(im), [dict(a) for a in anns]))
    if not rows:
        raise ValueError('Không có nhãn đã chấp nhận để xuất.')
    if output_dir and str(output_dir).strip():
        dest = Path(output_dir.strip()).expanduser().resolve()
    else:
        stamp = time.strftime('%Y%m%d_%H%M%S')
        safe = ''.join(ch for ch in name if ch.isalnum() or ch in '-_')[:60] or 'dataset'
        dest = DATA_ROOT / 'exports' / f'{safe}_{stamp}'
        
    for split in ('train', 'val'):
        (dest / 'images' / split).mkdir(parents=True, exist_ok=True)
        (dest / 'labels' / split).mkdir(parents=True, exist_ok=True)
        
    manifest = []
    for image, anns in rows:
        split = 'val' if int(image['sha256'][:8], 16) % 5 == 0 else 'train'
        src = Path(image['path'])
        outname = f"{image['id']:06d}_{src.name}"
        shutil.copy2(src, dest / 'images' / split / outname)
        lines = []
        for a in anns:
            w = max(1, image['width'])
            h = max(1, image['height'])
            x1, y1, x2, y2 = a['x1'], a['y1'], a['x2'], a['y2']
            cx = (x1 + x2) / (2 * w)
            cy = (y1 + y2) / (2 * h)
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            if a['class_id'] not in range(len(CLASSES)) or bw <= 0 or bh <= 0:
                continue
            lines.append(f"{a['class_id']} {cx:.7f} {cy:.7f} {bw:.7f} {bh:.7f}")
        (dest / 'labels' / split / (Path(outname).stem + '.txt')).write_text('\n'.join(lines) + '\n')
        manifest.append({'image_id': image['id'], 'source': image['path'], 'file': f'images/{split}/{outname}', 'labels': len(lines)})
        
    yaml = 'path: .\ntrain: images/train\nval: images/val\nnames:\n' + ''.join(f'  {i}: {name}\n' for i, name in enumerate(CLASSES))
    (dest / 'data.yaml').write_text(yaml)
    (dest / 'classes.txt').write_text('\n'.join(CLASSES) + '\n')
    (dest / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (dest / 'README.txt').write_text('Export dataset YOLO Detection. Tệp ảnh đã được sao chép; dữ liệu nguồn không bị thay đổi. Chỉ các nhãn accepted=1 được xuất. Đối chiếu manifest.json.\n')
    return {'path': str(dest), 'images': len(manifest), 'classes': CLASSES, 'data_yaml': str(dest / 'data.yaml')}
