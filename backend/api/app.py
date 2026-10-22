import json, os, subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from ..core.config import APP_ROOT, DATA_ROOT, DB_PATH, DEFAULT_MODEL, CLASSES
from ..database.store import connect, init_db
from ..dataset.operations import import_folder, export_dataset, clear_dataset
from ..pipeline.worker import JobRunner
from ..detection.models import ModelHub, ModelError
from ..core.hardware import detect_runtime, SUPPORTED

init_db(); runner=JobRunner(); probe=ModelHub()
app=FastAPI(title='AutoLabel AI Studio',version='0.3.0')

@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

class ImportRequest(BaseModel):
    folder: str
    clear_first: bool = False

class StartRequest(BaseModel):
    yolo_model: str = Field(default_factory=lambda: str(DEFAULT_MODEL))
    device: str = Field('auto', pattern='^(auto|cpu|cuda|mps)$')
    dino_model: str | None = None
    sam_model: str | None = None
    yolo_conf: float = Field(.25, ge=0, le=1)
    imgsz: int = Field(960, ge=320, le=2048)
    mode: str = 'standard'
    dino_box_threshold: float = Field(.28, ge=0, le=1)
    dino_text_threshold: float = Field(.25, ge=0, le=1)
    match_iou: float = Field(.4, ge=0, le=1)
    auto_accept: bool = False
    accept_yolo_only: bool = False
    output_dir: str | None = None

class ReviewItem(BaseModel): id:int|None=None; class_name:str; box:list[float]; accepted:bool=True; metadata:dict|None=None
class ReviewRequest(BaseModel): annotations:list[ReviewItem]
class ExportRequest(BaseModel):
    name: str = 'autolabel'
    output_dir: str | None = None

class ROIRequest(BaseModel): config:dict
class TrafficLabelRequest(BaseModel): label:str; accepted:bool=True
class TrafficExportRequest(BaseModel): name:str='traffic'; mode:str='extended'
class ClassificationExportRequest(BaseModel): name:str='traffic_classification'; include_pseudo:bool=False

@app.get('/api/health')
def health():
    info = detect_runtime()
    info.update({'status': 'ok', 'yolo_loaded': runner.hub.yolo_path,
                 'dino_loaded': runner.hub.dino_path, 'sam_loaded': runner.hub.sam_path,
                 'inference_device': runner.hub.device if runner.hub.yolo else info['device'],
                 'fallback_reason': runner.hub.fallback_reason,
                 'default_yolo': str(DEFAULT_MODEL), 'default_yolo_exists': DEFAULT_MODEL.is_file(),
                 'default_dino': str(APP_ROOT / 'checkpoints' / 'grounding-dino-tiny')
                       if (APP_ROOT / 'checkpoints' / 'grounding-dino-tiny' / 'model.safetensors').is_file() else '',
                 'default_sam': str(APP_ROOT / 'checkpoints' / 'sam-vit-base')
                       if (APP_ROOT / 'checkpoints' / 'sam-vit-base' / 'model.safetensors').is_file() else '',
                 'workspace': str(DATA_ROOT)})
    return info

@app.get('/api/model/check')
def model_check(path:str|None=None,device:str='auto'):
 p=path or str(DEFAULT_MODEL)
 try:return probe.load_yolo(p,device)
 except ModelError as e: raise HTTPException(400,str(e))

@app.post('/api/datasets/import')
def dataset_import(req:ImportRequest):
 try:return import_folder(req.folder, clear_first=req.clear_first)
 except Exception as e:raise HTTPException(400,str(e))

@app.post('/api/datasets/clear')
def dataset_clear():
 if runner.thread and runner.thread.is_alive():
  raise HTTPException(409, 'Hãy dừng job và chờ worker kết thúc trước khi xóa dataset.')
 return clear_dataset()

@app.get('/api/images')
def images(q:str='',status:str='all',limit:int=200,offset:int=0):
 limit=max(1,min(limit,500))
 with connect() as db:
  where=[]; args=[]
  if status!='all':where.append('i.status=?');args.append(status)
  if q:where.append('i.rel_path LIKE ?');args.append('%'+q+'%')
  sql='SELECT i.*, (SELECT count(*) FROM annotations a WHERE a.image_id=i.id) object_count FROM images i'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY i.id LIMIT ? OFFSET ?'
  rows=db.execute(sql,(*args,limit,offset)).fetchall(); total=db.execute('SELECT count(*) FROM images i'+(' WHERE '+' AND '.join(where) if where else ''),args).fetchone()[0]
 return {'items':[dict(x) for x in rows],'total':total}

@app.get('/api/images/{image_id}/file')
def image_file(image_id:int):
 with connect() as db:r=db.execute('SELECT path FROM images WHERE id=?',(image_id,)).fetchone()
 if not r:raise HTTPException(404,'Không tìm thấy ảnh')
 p=Path(r['path'])
 if not p.is_file():raise HTTPException(404,'Tệp ảnh gốc không còn tồn tại')
 return FileResponse(p)

@app.get('/api/masks/{filename}')
def mask_file(filename:str):
 import re
 if not re.fullmatch(r'\d+_\d+\.png',filename): raise HTTPException(404,'Mask không hợp lệ')
 path=DATA_ROOT/'masks'/filename
 if not path.is_file(): raise HTTPException(404,'Không tìm thấy SAM mask')
 return FileResponse(path,media_type='image/png')

@app.get('/api/images/{image_id}')
def image_detail(image_id:int):
 with connect() as db:
  im=db.execute('SELECT * FROM images WHERE id=?',(image_id,)).fetchone()
  if not im:raise HTTPException(404,'Không tìm thấy ảnh')
  anns=db.execute('SELECT * FROM annotations WHERE image_id=? ORDER BY id',(image_id,)).fetchall()
  res=[]
  for a in anns:
   d=dict(a); d['metadata']=json.loads(d.get('metadata') or '{}'); res.append(d)
  return {'image':dict(im),'annotations':res}

@app.put('/api/images/{image_id}/annotations')
@app.put('/api/images/{image_id}/review')
def image_save_annotations(image_id:int,req:ReviewRequest):
 with connect() as db:
  im=db.execute('SELECT * FROM images WHERE id=?',(image_id,)).fetchone()
  if not im:raise HTTPException(404,'Không tìm thấy ảnh')
  current_by={r['id']:dict(r) for r in db.execute('SELECT * FROM annotations WHERE image_id=?',(image_id,)).fetchall()}
  keep=set()
  for item in req.annotations:
   name=item.class_name
   if name not in (*CLASSES,'ambiguous'): raise HTTPException(422,'Class không hợp lệ: '+name)
   if name=='ambiguous' and item.accepted: raise HTTPException(422,'Nhãn ambiguous không thể accepted.')
   class_id=CLASSES.index(name) if name in CLASSES else -1
   if len(item.box)!=4: raise HTTPException(422,'Box cần đúng 4 tọa độ.')
   import math
   x1,y1,x2,y2=item.box
   if (not all(math.isfinite(v) for v in item.box) or not (0<=x1<x2<=im['width'])
       or not (0<=y1<y2<=im['height'])): raise HTTPException(422,'Box nằm ngoài ảnh hoặc kích thước không hợp lệ.')
   metadata=item.metadata or {}
   after={'class_name':name,'class_id':class_id,'box':[x1,y1,x2,y2],'accepted':item.accepted,'metadata':metadata}
   if item.id is not None and item.id not in current_by:
    raise HTTPException(409,'Annotation đã thay đổi/xóa: '+str(item.id))
   if item.id and item.id in current_by:
    keep.add(item.id)
    before=current_by[item.id]
    db.execute('INSERT INTO annotation_history(annotation_id,image_id,action,before_json,after_json) VALUES(?,?,?,?,?)',(item.id,image_id,'update',json.dumps(before),json.dumps(after)))
    db.execute("UPDATE annotations SET class_name=?,class_id=?,x1=?,y1=?,x2=?,y2=?,accepted=?,metadata=?,reviewed=1,source=CASE WHEN source='original' THEN 'original' ELSE 'manual' END,version=version+1 WHERE id=?",(name,class_id,x1,y1,x2,y2,int(item.accepted),json.dumps(metadata,ensure_ascii=False),item.id))
   else:
    cur=db.execute("INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,quality,accepted,reviewed,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,1,?)",(image_id,'manual',name,class_id,x1,y1,x2,y2,'human_reviewed',int(item.accepted),json.dumps(metadata,ensure_ascii=False)))
    aid=cur.lastrowid;db.execute('INSERT INTO annotation_history(annotation_id,image_id,action,after_json) VALUES(?,?,?,?)',(aid,image_id,'create',json.dumps(after)))
  for aid,before in current_by.items():
   if aid not in keep:
    db.execute('INSERT INTO annotation_history(annotation_id,image_id,action,before_json) VALUES(?,?,?,?)',(aid,image_id,'delete',json.dumps(before)))
    db.execute('DELETE FROM annotations WHERE id=?',(aid,))
 return {'saved':True,'count':len(req.annotations)}

@app.get('/api/stats')
def stats():
 with connect() as db:
  counts={r['status']:r['n'] for r in db.execute('SELECT status,count(*) n FROM images GROUP BY status')}
  qualities={r['quality'] or 'unknown':r['n'] for r in db.execute('SELECT quality,count(*) n FROM annotations GROUP BY quality')}
  classes={r['class_name']:r['n'] for r in db.execute('SELECT class_name,count(*) n FROM annotations WHERE accepted=1 GROUP BY class_name')}
  objects=db.execute('SELECT count(*) FROM annotations WHERE accepted=1').fetchone()[0]
  reviewed=db.execute('SELECT count(*) FROM annotations WHERE reviewed=1').fetchone()[0]
  last=db.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 1').fetchone()
 return {'images':sum(counts.values()),'statuses':counts,'objects':objects,'classes':classes,'quality':qualities,'reviewed':reviewed,'job':dict(last) if last else None}

@app.post('/api/jobs/start')
def job_start(req:StartRequest):
 cfg=req.model_dump()
 if not Path(cfg['yolo_model']).expanduser().is_file():raise HTTPException(400,'Đường dẫn best.pt không hợp lệ')
 try:jid=runner.start(cfg)
 except Exception as e:raise HTTPException(409,str(e))
 return {'job_id':jid,'state':'running'}

@app.post('/api/jobs/{action}')
def job_action(action:str):
 if action=='pause':runner.pause()
 elif action=='resume':runner.resume()
 elif action=='stop':runner.stop()
 elif action=='cancel':runner.cancel()
 else:raise HTTPException(404,'Action không hợp lệ')
 return stats()['job'] or {'state':'idle'}

@app.post('/api/jobs/resume')
def job_resume():
 try:return {'job_id':runner.start({},resume=True),'state':'running'}
 except Exception as e:raise HTTPException(409,str(e))

@app.get('/api/logs')
def logs(limit:int=100):
 with connect() as db:return {'items':[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?',(max(1,min(limit,500)),))]}

@app.post('/api/export')
def do_export(req:ExportRequest):
 try:return export_dataset(req.name, req.output_dir)
 except Exception as e:raise HTTPException(400,str(e))

from ..traffic import analysis as traffic

@app.get('/api/cameras')
def list_cameras(): return traffic.cameras()

@app.get('/api/cameras/{camera_id}/roi')
def read_camera_roi(camera_id:str): return traffic.get_roi(camera_id) or {'rois':[],'calibration':{},'calibration_confirmed':False}

@app.put('/api/cameras/{camera_id}/roi')
def write_camera_roi(camera_id:str,req:ROIRequest):
 try:return traffic.save_roi(camera_id,req.config)
 except Exception as e:raise HTTPException(400,str(e))

@app.post('/api/traffic/analyze')
def traffic_analyze():
 try:return traffic.analyze_all()
 except Exception as e:raise HTTPException(500,str(e))

@app.get('/api/traffic/labels')
def traffic_labels(limit:int=500,review_only:bool=False):
 rows=traffic.list_labels(limit,review_only)
 for r in rows:r['features']=json.loads(r.pop('features_json'))
 return {'items':rows,'total':len(rows)}

@app.put('/api/traffic/labels/{image_id}')
def traffic_label_review(image_id:int,req:TrafficLabelRequest):
 try:return traffic.set_label(image_id,req.label,req.accepted)
 except Exception as e:raise HTTPException(400,str(e))

@app.post('/api/traffic/export-classification')
def traffic_classification_export(req:ClassificationExportRequest):
 try:return traffic.export_classification(req.name,req.include_pseudo)
 except Exception as e:raise HTTPException(400,str(e))

@app.get('/api/traffic/temporal')
def traffic_temporal():return {'items':traffic.temporal_records()}

@app.post('/api/traffic/export')
def traffic_export(req:TrafficExportRequest):
 try:return traffic.export_traffic(req.name,req.mode)
 except Exception as e:raise HTTPException(400,str(e))

static=APP_ROOT/'frontend'/'dist'
if static.exists():app.mount('/',StaticFiles(directory=static,html=True),name='frontend')
