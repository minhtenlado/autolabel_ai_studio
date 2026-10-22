import csv,json,re,time
from datetime import datetime,timezone
from pathlib import Path
from ..database.store import connect
from ..core.config import DATA_ROOT,CLASSES
TRAFFIC_CLASSES=['Thong_thoang','Dong_xe','Un_u_nhe','Un_tac_nang']
def inside(pt,poly):
 x,y=pt; ok=False;j=len(poly)-1
 for i,(xi,yi) in enumerate(poly):
  xj,yj=poly[j]
  if (yi>y)!=(yj>y) and x<(xj-xi)*(y-yi)/(yj-yi+1e-15)+xi:ok=not ok
  j=i
 return ok
def get_roi(cam):
 with connect() as db:r=db.execute('SELECT config FROM camera_configs WHERE camera_id=?',(cam,)).fetchone()
 return json.loads(r[0]) if r else None
def save_roi(cam,cfg):
 if not cam or len(cam)>120:raise ValueError('camera_id không hợp lệ')
 for roi in cfg.get('rois',[]):
  if roi.get('type') not in ('road','lane','exclusion','queue') or len(roi.get('polygon',[]))<3:raise ValueError('ROI cần type road/lane/exclusion/queue và ít nhất 3 điểm')
  if any(len(p)!=2 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in p) for p in roi['polygon']):raise ValueError('Tọa độ polygon cần chuẩn hóa 0..1')
 cal=cfg.get('calibration',{})
 if cal and not (0<=cal['free_max']<cal['busy_max']<cal['queue_min']<=cal['jam_min']):raise ValueError('Ngưỡng cần tăng dần: free_max < busy_max < queue_min <= jam_min')
 cfg={'rois':cfg.get('rois',[]),'calibration':cal,'calibration_confirmed':bool(cfg.get('calibration_confirmed',False)),'updated_at':datetime.now(timezone.utc).isoformat()}
 with connect() as db:db.execute('INSERT INTO camera_configs(camera_id,config) VALUES(?,?) ON CONFLICT(camera_id) DO UPDATE SET config=excluded.config,updated_at=CURRENT_TIMESTAMP',(cam,json.dumps(cfg,ensure_ascii=False)))
 return cfg
def cameras():
 with connect() as db:return [dict(r) for r in db.execute('SELECT camera_id,count(*) image_count,min(timestamp) first_timestamp,max(timestamp) last_timestamp FROM images GROUP BY camera_id ORDER BY camera_id')]
def analyze_all():
 out=[]
 with connect() as db:
  ims=db.execute('SELECT * FROM images ORDER BY camera_id,timestamp,id').fetchall();cfgs={r['camera_id']:json.loads(r['config']) for r in db.execute('SELECT * FROM camera_configs')}
  for im in ims:
   cfg=cfgs.get(im['camera_id'],{});road=next((r['polygon'] for r in cfg.get('rois',[]) if r['type']=='road' and r.get('status','confirmed')=='confirmed'),None); anns=db.execute("SELECT * FROM annotations WHERE image_id=?",(im['id'],)).fetchall();counts={n:0 for n in CLASSES};uncertain=0;boxarea=0
   for a in anns:
    cx=(a['x1']+a['x2'])/2/max(1,im['width']);cy=(a['y1']+a['y2'])/2/max(1,im['height'])
    if road and not inside((cx,cy),road):continue
    if a['class_name'] in counts:counts[a['class_name']]+=1
    else:uncertain+=1
    if road:boxarea+=max(0,(a['x2']-a['x1'])*(a['y2']-a['y1']))
   total=sum(counts.values());occ=None
   if road:
    area=abs(sum(road[i][0]*road[(i+1)%len(road)][1]-road[(i+1)%len(road)][0]*road[i][1] for i in range(len(road))))/2*im['width']*im['height'];occ=min(1,boxarea/area) if area else None
   cal=cfg.get('calibration',{});label=None;reasons=[]
   if not road:reasons.append('missing_confirmed_road_roi')
   if not im['timestamp']:reasons.append('missing_timestamp_image_only_mode')
   if not anns:reasons.append('missing_detection_annotations')
   if uncertain:reasons.append('uncertain_vehicle_count')
   if not cal:reasons.append('camera_thresholds_not_calibrated')
   if cal:
    label='Thong_thoang' if total<=cal['free_max'] else 'Dong_xe' if total<=cal['busy_max'] else 'Un_u_nhe' if total<cal['jam_min'] else 'Un_tac_nang'
   quality='high_quality_candidate' if road and cal and cfg.get('calibration_confirmed') and anns and not uncertain else 'needs_review'
   f={'camera_id':im['camera_id'],'timestamp':im['timestamp'],'counts':counts,'total_vehicle_count':total,'uncertain_vehicle_count':uncertain,'road_pixel_occupancy':None,'box_occupancy_proxy':occ,'occupancy_source':'bounding_box_area_proxy' if occ is not None else 'unavailable','relative_density':total if road else None,'queue_indicator':'unavailable','predicted_traffic_class':label,'class_id':TRAFFIC_CLASSES.index(label) if label else None,'quality_score':0.75 if quality=='high_quality_candidate' else (0.4 if label else None),'review_status':quality,'label_source':'camera_rule_pseudo_label' if label else 'unavailable','reasons':reasons,'image_path':im['path'],'annotation_version':max([a['version'] for a in anns],default=0)}
   db.execute('INSERT INTO traffic_measurements(image_id,camera_id,timestamp,features_json,predicted_class,quality,review_status) VALUES(?,?,?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET camera_id=excluded.camera_id,timestamp=excluded.timestamp,features_json=excluded.features_json,predicted_class=CASE WHEN traffic_measurements.review_status="accepted" THEN traffic_measurements.predicted_class ELSE excluded.predicted_class END,quality=CASE WHEN traffic_measurements.review_status="accepted" THEN traffic_measurements.quality ELSE excluded.quality END,review_status=CASE WHEN traffic_measurements.review_status="accepted" THEN "accepted" ELSE excluded.review_status END',(im['id'],im['camera_id'],im['timestamp'],json.dumps(f,ensure_ascii=False),label,quality,quality));out.append({'image_id':im['id'],'rel_path':im['rel_path'],**f})
 return {'processed':len(out),'labeled':sum(bool(x['predicted_traffic_class']) for x in out),'needs_review':sum(x['review_status']=='needs_review' for x in out),'items':out[:200]}
def list_labels(limit=500,review_only=False):
 sql='SELECT t.*,i.rel_path FROM traffic_measurements t JOIN images i ON i.id=t.image_id'+(' WHERE t.review_status="needs_review"' if review_only else '')+' ORDER BY COALESCE(t.timestamp,""),t.image_id LIMIT ?'
 with connect() as db:return [dict(r) for r in db.execute(sql,(max(1,min(limit,2000)),))]
def set_label(iid,label,accepted=True):
 if label not in TRAFFIC_CLASSES:raise ValueError('Nhãn không hợp lệ')
 with connect() as db:
  r=db.execute('SELECT features_json FROM traffic_measurements WHERE image_id=?',(iid,)).fetchone()
  if not r:raise ValueError('Chưa phân tích ảnh')
  f=json.loads(r[0]);f['review_status']='accepted' if accepted else 'rejected';f['label_source']='human_verified';f['verified_by_human']=True
  db.execute('UPDATE traffic_measurements SET features_json=?,predicted_class=?,quality=?,review_status=? WHERE image_id=?',(json.dumps(f,ensure_ascii=False),label,'human_verified',f['review_status'],iid))
 return {'image_id':iid,'label':label,'review_status':f['review_status']}
def temporal_records():
 rows=list_labels(2000);groups={}
 for r in rows:
  if r['timestamp']:groups.setdefault(r['camera_id'],[]).append(r)
 out=[]
 for cam,rs in groups.items():
  rs.sort(key=lambda r:r['timestamp']);prev=None;prev_count=None
  for r in rs:
   try:ts=datetime.fromisoformat(r['timestamp'])
   except Exception:continue
   f=json.loads(r['features_json']);delta=(ts-prev).total_seconds() if prev else None
   out.append({'camera_id':cam,'timestamp':ts.isoformat(sep=' '),'interval_seconds':delta,'gap_over_13s':bool(delta is not None and delta>13),'bus_count':f['counts'].get('bus',0),'car_count':f['counts'].get('car',0),'container_count':f['counts'].get('container',0),'motorcycle_count':f['counts'].get('motorcycle',0),'truck_count':f['counts'].get('truck',0),'total_vehicle_count':f['total_vehicle_count'],'road_pixel_occupancy':f['road_pixel_occupancy'],'box_occupancy_proxy':f['box_occupancy_proxy'],'relative_density':f['relative_density'],'queue_indicator':'unavailable','density_trend':None if prev_count is None else f['total_vehicle_count']-prev_count,'traffic_class_id':f['class_id'],'traffic_class_name':f['predicted_traffic_class'],'detection_quality':'provisional','classification_quality':f['review_status'],'review_status':f['review_status'],'label_source':f['label_source'],'image_path':f['image_path'],'annotation_version':f['annotation_version'],'model_versions':None,'observed':True,'interpolated':False,'carried_forward':False});prev=ts;prev_count=f['total_vehicle_count']
 return out
def export_traffic(name='traffic',mode='extended'):
 if mode=='legacy':raise ValueError('Legacy 46-feature export khóa: thiếu schema/normalizer TCN đã xác minh.')
 rows=temporal_records()
 if not rows:raise ValueError('Chưa có timestamp hợp lệ để xuất chuỗi.')
 dest=DATA_ROOT/'exports'/('traffic_'+''.join(c for c in name if c.isalnum() or c in '-_')[:40]+'_'+time.strftime('%Y%m%d_%H%M%S'));dest.mkdir(parents=True,exist_ok=False)
 with (dest/'traffic_extended.csv').open('w',newline='',encoding='utf-8-sig') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 (dest/'schema.json').write_text(json.dumps({'mode':'extended_traffic_features','legacy_compatible':False,'timestamp_policy':'observed only; no synthetic missing steps','pseudo_labels_are_not_ground_truth':True},indent=2))
 return {'path':str(dest),'records':len(rows),'mode':'extended','legacy_compatible':False}


def export_classification(name='traffic_classification',include_pseudo=False):
    import hashlib,shutil
    with connect() as db:
        rows=db.execute('SELECT t.*,i.path,i.sha256,i.rel_path FROM traffic_measurements t JOIN images i ON i.id=t.image_id WHERE t.predicted_class IS NOT NULL ORDER BY t.image_id').fetchall()
    chosen=[]
    for r in rows:
        f=json.loads(r['features_json'])
        if r['review_status']=='accepted' and f.get('label_source')=='human_verified':chosen.append((r,f,False))
        elif include_pseudo and r['review_status']=='high_quality_candidate':chosen.append((r,f,True))
    if not chosen:raise ValueError('Không có nhãn classification phù hợp để xuất. Hãy xác nhận nhãn bằng con người; pseudo-label chỉ xuất khi được bật rõ ràng.')
    dest=DATA_ROOT/'exports'/('classification_'+''.join(c for c in name if c.isalnum() or c in '-_')[:40]+'_'+time.strftime('%Y%m%d_%H%M%S'));dest.mkdir(parents=True,exist_ok=False)
    manifest=[]; groups={}
    for r,f,pseudo in chosen:
        # Keep frames from the same camera-day together where timestamps exist.
        try:day=datetime.fromisoformat(r['timestamp']).date().isoformat()
        except Exception:day=None
        group=(r['camera_id']+':'+day) if day else ('image:'+r['sha256'])
        groups[group]=groups.get(group,0)
    split_by_group={g:('val' if int(hashlib.sha256(g.encode()).hexdigest()[:8],16)%5==0 else 'train') for g in groups}
    for r,f,pseudo in chosen:
        split=split_by_group[(r['camera_id']+':'+datetime.fromisoformat(r['timestamp']).date().isoformat()) if r['timestamp'] else ('image:'+r['sha256'])]
        src=Path(r['path'])
        if not src.is_file():continue
        target=dest/split/r['predicted_class']/f"{r['image_id']:07d}_{src.name}";target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
        manifest.append({'image_id':r['image_id'],'source':str(src),'file':str(target.relative_to(dest)),'camera_id':r['camera_id'],'timestamp':r['timestamp'],'class':r['predicted_class'],'label_source':f['label_source'],'pseudo_label':pseudo,'split':split})
    if not manifest:raise ValueError('Không tìm thấy ảnh nguồn còn tồn tại.')
    groups_method='camera_day' if all(':' in g and not g.startswith('image:') for g in groups) else 'image_hash_fallback_no_timestamp'
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    (dest/'README.txt').write_text('Classification folder export. Original files are copied, not modified. Confirmed human labels only by default.\nSplit grouping: '+groups_method+'\nIf timestamps are missing, image-hash split cannot guarantee camera-session leakage control. Review manifest before training.\n')
    return {'path':str(dest),'images':len(manifest),'pseudo_labels':sum(m['pseudo_label'] for m in manifest),'split_method':groups_method,'train':sum(m['split']=='train' for m in manifest),'val':sum(m['split']=='val' for m in manifest)}
