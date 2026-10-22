from pathlib import Path
import re
from PIL import Image
from ..consensus.engine import Detection
from ..core.config import CLASSES
from ..core.hardware import select_device, configure_cpu_threads, is_accelerator_error, preference, DeviceUnavailable

class ModelError(RuntimeError): pass

class ModelHub:
    def __init__(self):
        self.yolo=None; self.yolo_path=None; self.dino=None; self.dino_processor=None; self.dino_path=None; self.sam=None; self.sam_processor=None; self.sam_path=None; self.device='cpu'; self.torch=None; self.dino_device='cpu'; self.sam_device='cpu'; self.fallback_reason=None; self.device_preference=preference()

    def _torch(self):
        if self.torch is None:
            try:
                import torch
            except (ImportError, OSError) as exc:
                raise ModelError('Chưa cài PyTorch: chạy setup và cài AI dependencies. ' + str(exc)) from exc
            self.torch=torch
            configure_cpu_threads(torch)
            # Device is selected when loading a model, so per-job UI choice can
            # override even an unavailable default environment preference.
        return self.torch

    def load_yolo(self, path, requested_device=None):
        p=Path(path).expanduser().resolve()
        if not p.is_file(): raise ModelError(f'Không tìm thấy checkpoint YOLO: {p}')
        torch=self._torch()
        self.device_preference = preference(requested_device)
        try:
            self.device = select_device(torch, self.device_preference)
        except DeviceUnavailable as exc:
            raise ModelError(str(exc)) from exc
        self.fallback_reason = None
        try:
            from ultralytics import YOLO
            model=YOLO(str(p), task='detect')
            names=model.names
            names={int(k):str(v).strip().lower() for k,v in names.items()} if isinstance(names,dict) else {i:str(v).strip().lower() for i,v in enumerate(names)}
            available=set(names.values())
            # No silent numeric-ID assumptions. Require an explicit class mapping if names are incompatible.
            missing=sorted(set(CLASSES)-available)
            if missing: raise ModelError(f'Checkpoint thiếu class theo tên: {missing}. Class trong model: {names}')
            self.yolo=model; self.yolo_path=str(p)
            return {'path':str(p),'names':names,'device':self.device,'cuda_available':torch.cuda.is_available(),'vram_total_mb':round(torch.cuda.get_device_properties(0).total_memory/1048576) if torch.cuda.is_available() else 0, 'fallback_reason':self.fallback_reason}
        except ModelError: raise
        except Exception as e: raise ModelError(f'Không tải được checkpoint YOLO: {e}') from e

    def yolo_predict(self, image, conf=.25, imgsz=960, mode='standard'):
        if self.yolo is None: raise ModelError('Chưa tải model YOLO.')
        # Small-object mode uses overlapping tiles; coordinates are remapped to source image.
        width,height=image.size; out=[]
        if mode=='small_object':
            tile=min(1280,max(640,int(imgsz))); overlap=.18; step=max(1,int(tile*(1-overlap)))
            xs=list(range(0,max(1,width-tile+1),step)); ys=list(range(0,max(1,height-tile+1),step))
            if not xs or xs[-1]+tile<width: xs.append(max(0,width-tile))
            if not ys or ys[-1]+tile<height: ys.append(max(0,height-tile))
            regions=[(x,y,min(width,x+tile),min(height,y+tile)) for y in ys for x in xs]
        else: regions=[(0,0,width,height)]
        for x1,y1,x2,y2 in regions:
            crop=image.crop((x1,y1,x2,y2))
            # Single-image batches bound accelerator memory; an automatic GPU
            # fallback retries this image on CPU after a runtime device failure.
            try:
                result=self.yolo.predict(crop,conf=conf,imgsz=imgsz,device=self.device,verbose=False)[0]
            except (RuntimeError, AssertionError, ValueError) as exc:
                if self.device == 'cpu' or self.device_preference != 'auto' or not is_accelerator_error(exc):
                    raise
                self.fallback_reason = str(exc)[:350]
                self.device = 'cpu'
                if self.torch and hasattr(self.torch, 'cuda') and self.torch.cuda.is_available():
                    self.torch.cuda.empty_cache()
                result=self.yolo.predict(crop,conf=conf,imgsz=min(imgsz,640),device='cpu',verbose=False)[0]
            if result.boxes is None: continue
            for box in result.boxes:
                c=int(box.cls[0].item()); name=str(self.yolo.names[c]).strip().lower()
                if name not in CLASSES: continue
                xy=box.xyxy[0].detach().cpu().tolist()
                mapped=[xy[0]+x1,xy[1]+y1,xy[2]+x1,xy[3]+y1]
                out.append(Detection(name,mapped,float(box.conf[0].item()),'yolo'))
        # NMS across tile edges: class-wise greedy IoU suppression.
        kept=[]
        from ..consensus.engine import iou
        for d in sorted(out,key=lambda x:x.score,reverse=True):
            if not any(k.class_name==d.class_name and iou(k.box,d.box)>.55 for k in kept): kept.append(d)
        return kept

    def load_dino(self,path):
        p=Path(path).expanduser().resolve()
        if not p.exists(): raise ModelError(f'Không tìm thấy thư mục/checkpoint Grounding DINO: {p}')
        try:
            torch=self._torch()
            from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
            processor=AutoProcessor.from_pretrained(str(p),local_files_only=True)
            model=AutoModelForZeroShotObjectDetection.from_pretrained(str(p),local_files_only=True)
            try:
                model=model.to(self.device).eval(); self.dino_device=self.device
            except (RuntimeError, AssertionError) as exc:
                if self.device == 'cpu' or self.device_preference != 'auto' or not is_accelerator_error(exc): raise
                self.dino_device='cpu'; self.fallback_reason=str(exc)[:350]; model=model.to('cpu').eval()
            self.dino_processor=processor; self.dino=model; self.dino_path=str(p)
            return {'path':str(p),'device':self.dino_device}
        except Exception as e: raise ModelError(f'Không nạp được Grounding DINO cục bộ. Cần model + processor tương thích Hugging Face: {e}') from e

    def dino_predict(self,image,box_threshold=.28,text_threshold=.25):
        if self.dino is None:return []
        import torch
        prompts=['bus','passenger bus','city bus','car','passenger car','sedan','suv','motorcycle','motorbike','scooter','container truck','semi truck carrying a shipping container','shipping container truck','cargo truck','delivery truck','truck']
        try:
            inputs=self.dino_processor(images=image,text=' . '.join(prompts)+' .',return_tensors='pt').to(self.dino_device)
            with torch.inference_mode(): outputs=self.dino(**inputs)
        except (RuntimeError, AssertionError) as exc:
            if self.dino_device == 'cpu' or self.device_preference != 'auto' or not is_accelerator_error(exc): raise
            self.fallback_reason=str(exc)[:350]; self.dino_device='cpu'; self.dino=self.dino.to('cpu')
            inputs=self.dino_processor(images=image,text=' . '.join(prompts)+' .',return_tensors='pt').to('cpu')
            with torch.inference_mode(): outputs=self.dino(**inputs)
        postprocess=self.dino_processor.post_process_grounded_object_detection
        import inspect
        params=inspect.signature(postprocess).parameters
        threshold_arg='threshold' if 'threshold' in params else 'box_threshold'
        proc=postprocess(outputs,inputs.input_ids,**{threshold_arg:box_threshold,'text_threshold':text_threshold,'target_sizes':[image.size[::-1]]})[0]
        detections=[]
        for box,score,label in zip(proc['boxes'],proc['scores'],proc['text_labels']):
            raw=str(label).lower().strip().strip('.'); chosen=None
            # Prefer exact known phrase; longest phrase wins, avoiding 'car' inside 'cargo truck'.
            for phrase,cls in sorted([('passenger bus','bus'),('city bus','bus'),('bus','bus'),('passenger car','car'),('car','car'),('sedan','car'),('suv','car'),('motorcycle','motorcycle'),('motorbike','motorcycle'),('scooter','motorcycle'),('container truck','container'),('semi truck carrying a shipping container','container'),('shipping container truck','container'),('cargo truck','truck'),('delivery truck','truck'),('truck','truck')],key=lambda x:len(x[0]),reverse=True):
                if re.search(r'(?<![a-z])'+re.escape(phrase)+r'(?![a-z])',raw): chosen=cls; break
            ambiguous=chosen is None
            detections.append(Detection(chosen or 'ambiguous',[float(v) for v in box.tolist()],float(score),'grounding_dino',ambiguous))
        return detections

    def load_sam(self,path):
        p=Path(path).expanduser().resolve()
        if not p.exists(): raise ModelError(f'Không tìm thấy checkpoint SAM cục bộ: {p}')
        try:
            self._torch()
            from transformers import SamModel, SamProcessor
            model=SamModel.from_pretrained(str(p),local_files_only=True)
            processor=SamProcessor.from_pretrained(str(p),local_files_only=True)
            try:
                model=model.to(self.device).eval(); self.sam_device=self.device
            except (RuntimeError, AssertionError) as exc:
                if self.device == 'cpu' or self.device_preference != 'auto' or not is_accelerator_error(exc): raise
                self.sam_device='cpu'; self.fallback_reason=str(exc)[:350]; model=model.to('cpu').eval()
            self.sam=model; self.sam_processor=processor; self.sam_path=str(p)
            return {'path':str(p),'device':self.sam_device}
        except Exception as e: raise ModelError(f'Không nạp được SAM cục bộ (Hugging Face SamModel): {e}') from e

    def sam_refine(self,image,detections,mask_dir):
        if self.sam is None:return detections
        import numpy as np, torch
        from pathlib import Path
        mask_dir=Path(mask_dir); mask_dir.mkdir(parents=True,exist_ok=True)
        for idx,d in enumerate(detections):
            x1,y1,x2,y2=d['box']; boxes=[[[x1,y1,x2,y2]]]
            try:
                inputs=self.sam_processor(images=image,input_boxes=boxes,return_tensors='pt').to(self.sam_device)
                with torch.inference_mode(): outputs=self.sam(**inputs)
            except (RuntimeError, AssertionError) as exc:
                if self.sam_device == 'cpu' or self.device_preference != 'auto' or not is_accelerator_error(exc): raise
                self.fallback_reason=str(exc)[:350]; self.sam_device='cpu'; self.sam=self.sam.to('cpu')
                inputs=self.sam_processor(images=image,input_boxes=boxes,return_tensors='pt').to('cpu')
                with torch.inference_mode(): outputs=self.sam(**inputs)
            masks=self.sam_processor.post_process_masks(outputs.pred_masks.detach().cpu(),inputs.original_sizes.detach().cpu(),inputs.reshaped_input_sizes.detach().cpu())
            mask_set=masks[0][0]
            best_mask=int(outputs.iou_scores[0,0].argmax().item()) if getattr(outputs,'iou_scores',None) is not None else 0
            mask=mask_set[best_mask].detach().cpu().numpy().astype(bool)
            ys,xs=np.where(mask)
            if len(xs)==0: d['metadata']['sam']={'quality':'empty_mask'}; continue
            mb=[float(xs.min()),float(ys.min()),float(xs.max()+1),float(ys.max()+1)]
            ratio=float(mask.sum()/max(1,(x2-x1)*(y2-y1)))
            # A mask is only geometry evidence; class remains detector-derived. Keep original box unless plausible/stable.
            from ..consensus.engine import iou
            box_iou=iou(d['box'],mb)
            plausible=.08 <= ratio <= .98 and box_iou>=.25
            filename=f"{d['image_id']}_{idx}.png"
            from PIL import Image as PILImage
            PILImage.fromarray((mask*255).astype('uint8')).save(mask_dir/filename)
            d['metadata']['sam']={'mask_path':filename,'mask_area_ratio':round(ratio,4),'mask_box_iou':round(box_iou,4),'mask_derived_box':mb,'quality':'plausible' if plausible else 'suspicious'}
            if plausible:
                d['metadata']['original_box']=d['box']; d['metadata']['refinement_reason']='SAM mask geometry; suggestion only'
                # Keep original for review; UI can apply suggestion explicitly.
        return detections
