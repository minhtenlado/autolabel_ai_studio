
window.cancelJob = async function() {
  if (!confirm('Bạn có chắc chắn muốn HỦY BỎ tiến trình gán nhãn đang chạy không?')) return;
  try {
    await api('/api/jobs/cancel', {method: 'POST'});
    toast('Đã hủy bỏ job thành công');
    refreshAll();
  } catch(e) {
    toast(e.message, true);
  }
};

window.clearDataset = async function() {
  if (!confirm('CẢNH BÁO: Bạn có chắc chắn muốn xóa sạch toàn bộ danh sách ảnh và nhãn cũ để tải thư mục mới không?')) return;
  try {
    await api('/api/datasets/clear', {method: 'POST'});
    toast('Đã làm mới project thành công');
    loadImages();
    refreshAll();
  } catch(e) {
    toast(e.message, true);
  }
};
window.confirmCancelJob = window.cancelJob;
window.confirmClearDataset = window.clearDataset;


function confirmCancelJob(){
  if(confirm('Bạn có chắc chắn muốn HỦY BỎ tiến trình gán nhãn đang chạy không?')){
    jobAction('cancel');
  }
}

async function confirmClearDataset(){
  if(confirm('CẢNH BÁO: Bạn có chắc chắn muốn xóa sạch toàn bộ danh sách ảnh và nhãn cũ để tải thư mục mới hoàn toàn không?')){
    try{
      const r = await api('/api/datasets/clear', {method:'POST'});
      toast('Đã làm mới project thành công');
      loadImages();
      refreshAll();
    }catch(e){
      toast(e.message, true);
    }
  }
}

const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let currentView='dashboard', currentImage=null, currentAnnotations=[], images=[], queue=[], selectedAnn=-1, imgObj=null, canvasScale=1, canvasOffset={x:0,y:0}, drag=null, undoStack=[],redoStack=[],pollTimer,showMasks=false,showYolo=true,showDino=true,showFinal=true,spaceDown=false,maskCache={},imageOffset=0,imageTotal=0,queueOffset=0,queueTotal=0;
const classNames=['bus','car','container','motorcycle','truck'], colors={bus:'#7ce8b4',car:'#78b9ff',container:'#bea4ff',motorcycle:'#ffce72',truck:'#ff8b83'};
async function api(url,opts={}){const r=await fetch(url,{headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});let body;try{body=await r.json()}catch{body={}}if(!r.ok)throw Error(body.detail||`HTTP ${r.status}`);return body}
function toast(text,error=false){const t=$('#toast');t.textContent=text;t.className='toast show'+(error?' error':'');setTimeout(()=>t.className='toast',3400)}
function showView(name){currentView=name;$$('.view').forEach(x=>x.classList.toggle('active',x.id===name));$$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===name));const titles={dashboard:'Tổng quan dataset',dataset:'Dataset manager',labeling:'Auto labeling',review:'AI annotation review',traffic:'Traffic state & temporal analysis',export:'Export dataset'};$('#title').textContent=titles[name];$('#pageName').textContent=titles[name];if(name==='dataset')loadImages();if(name==='review')loadQueue();if(name==='traffic'){loadCameras();loadTraffic()}}
$$('.nav').forEach(b=>b.onclick=()=>showView(b.dataset.view));
async function refreshAll(){try{const [s,h]=await Promise.all([api('/api/stats'),api('/api/health')]);renderStats(s);renderHealth(h);}catch(e){toast(e.message,true)}}
function renderStats(s){const st=s.statuses||{};$('#sImages').textContent=(s.images||0).toLocaleString();$('#sPending').textContent=`${(st.pending||0).toLocaleString()} chờ · ${st.failed||0} lỗi`;$('#sProcessed').textContent=(st.processed||0).toLocaleString();$('#sObjects').textContent=(s.objects||0).toLocaleString();$('#sReviewed').textContent=`${s.reviewed||0} nhãn đã con người review`;const review=Number(s.quality?.needs_review||0)+Number(s.quality?.high_risk||0);$('#sReview').textContent=review.toLocaleString();$('#reviewBadge').textContent=review.toLocaleString();$('#jobState').textContent=(s.job?.state||'IDLE').toUpperCase();const pct=s.job?.total?Math.round(100*(s.job.processed||0)/s.job.total):0;$('#progressBar').style.width=pct+'%';$('#progressPct').textContent=pct+'%';$('#progressText').textContent=s.job?`${s.job.processed||0} / ${s.job.total} ảnh · ${s.job.failed||0} lỗi`:'Chưa có job';$('#currentFile').textContent=s.job?.current_path||'—';if(s.job?.state==='failed' && s.job.error)$('#startMessage').textContent='Lỗi pipeline: '+s.job.error;if(s.job?.started_at){const elapsed=Math.max(1,(Date.now()-Date.parse(s.job.started_at.replace(' ','T')+'Z'))/1000),speed=(s.job.processed||0)/elapsed,pending=Math.max(0,(s.job.total||0)-(s.job.processed||0)-(s.job.failed||0));$('#sSpeed').textContent=speed>0?`${speed.toFixed(2)} ảnh/s · còn ~${Math.ceil(pending/speed)} giây`:'Đang khởi động'}else $('#sSpeed').textContent='Ảnh hoàn tất';
  const jState = (s.job?.state || 'IDLE').toUpperCase();
  if($('#bannerJobBadge')) {
    $('#bannerJobBadge').textContent = jState;
    $('#bannerJobBadge').className = 'state-chip ' + (s.job?.state || 'idle');
    $('#bannerBar').style.width = pct + '%';
    $('#bannerPct').textContent = pct + '%';
    if(s.job?.state === 'cancelled') { $('#bannerProgressTxt').textContent = 'Job cũ đã hủy · Có ' + (st.pending||0) + ' ảnh đang chờ gán nhãn'; $('#bannerBar').style.width='0%'; $('#bannerPct').textContent='0%'; } else { $('#bannerProgressTxt').textContent = s.job ? (s.job.processed||0) + ' / ' + (s.job.total||0) + ' ảnh (' + pct + '%) · ' + (s.job.failed||0) + ' lỗi' : 'Chưa có job'; }
    $('#bannerCurFile').textContent = s.job?.current_path ? 'Đang chạy: ' + s.job.current_path.split(/[\\/]/).pop() : (s.job?.state === 'running' ? 'Đang xử lý...' : '—');
    if($('#bannerSpeedTxt') && $('#sSpeed')) $('#bannerSpeedTxt').textContent = $('#sSpeed').textContent;
  }
  if($('#labelingStateChip')) {
    $('#labelingStateChip').textContent = jState;
    $('#labelingStateChip').className = 'state-chip ' + (s.job?.state || 'idle');
    $('#labelingProgressBar').style.width = pct + '%';
    $('#labelingProgressPct').textContent = pct + '%';
    $('#labelingProgressText').textContent = s.job ? `${s.job.processed||0} / ${s.job.total||0} ảnh` : 'Chưa có job';
    $('#labelingCurrentFile').textContent = s.job?.current_path || '—';
  }

  renderChart(s.classes||{});}
function renderChart(data){const entries=classNames.map(n=>[n,Number(data[n]||0)]),max=Math.max(1,...entries.map(x=>x[1]));$('#classChart').innerHTML=entries.every(x=>!x[1])?'<div class="chart-empty">Chưa có annotation được chấp nhận</div>':entries.map(([n,v])=>`<div class="bar-item"><div class="bar-track"><div class="bar" style="height:${Math.max(2,82*v/max)}px;background:${colors[n]}"></div></div><b>${v}</b><small>${n}</small></div>`).join('')}
function renderHealth(h){
 const gpu=h.gpu||(h.device==='mps'?'Apple MPS':'CPU'), active=h.inference_device||h.device, accelerated=active!=='cpu';
 $('#gpuName').textContent=gpu;
 $('#gpuInfo').textContent=`Inference: ${active}${h.fallback_reason?' (CPU fallback)':''}`;
 $('#gpuLed').style.background=accelerated?'var(--mint)':'var(--amber)';
 $('#hardwareGpu').textContent=gpu;
 $('#hardwareCuda').textContent=`${active.toUpperCase()} · ${h.cuda?(h.rocm?'ROCm':'CUDA'):(h.mps?'MPS':'CPU')}${h.fallback_reason?' · GPU lỗi, đã fallback':''}`;
 $('#hardwareCuda').style.color=accelerated?'var(--mint)':'var(--amber)';
 $('#hardwareVram').textContent=h.vram_total_mb!=null?`${h.vram_used_mb??'—'} / ${h.vram_total_mb} MiB`:'—';
 $('#vramBar').style.width=h.vram_total_mb?Math.min(100,100*(h.vram_used_mb||0)/h.vram_total_mb)+'%':'0%';
 $('#hardwareRam').textContent=h.ram_total_mb?`${(h.ram_used_mb/1024).toFixed(1)} / ${(h.ram_total_mb/1024).toFixed(1)} GiB`:'—';
 $('#ramBar').style.width=h.ram_total_mb?Math.min(100,100*h.ram_used_mb/h.ram_total_mb)+'%':'0%';
 $('#loadedYolo').textContent=h.yolo_loaded?.split(/[\\/]/).pop()||'Chưa tải';
 $('#loadedDino').textContent=h.dino_loaded?'Đã tải':'Chưa cấu hình';
 $('#loadedSam').textContent=h.sam_loaded?'Đã tải':'Chưa cấu hình';
 for(const [id,key] of [['yoloPath','default_yolo'],['dinoPath','default_dino'],['samPath','default_sam']]){
   const input=$('#'+id);if(input && !input.dataset.touched && !input.value && h[key])input.value=h[key];
 }
}

async function importDataset(){const b=$('#importBtn');b.disabled=true;$('#importResult').textContent='Đang quét ảnh và tính SHA-256…';try{const r=await api('/api/datasets/import',{method:'POST',body:JSON.stringify({folder:$('#datasetPath').value.trim()})});$('#importResult').textContent=`Đã thêm ${r.added} ảnh · ${r.duplicates} ảnh trùng bỏ qua · ${r.broken} ảnh lỗi / ${r.scanned} ảnh tìm thấy.`;toast('Import dataset hoàn tất');loadImages();refreshAll()}catch(e){$('#importResult').textContent=e.message;toast(e.message,true)}finally{b.disabled=false}}
async function loadImages(reset=true){if(reset){imageOffset=0;images=[]}try{const q=encodeURIComponent($('#imageSearch')?.value||''),st=encodeURIComponent($('#statusFilter')?.value||'all');const r=await api(`/api/images?q=${q}&status=${st}&limit=100&offset=${imageOffset}`);images=reset?r.items:[...images,...r.items];imageOffset=images.length;imageTotal=r.total;$('#imageCount').textContent=r.total;$('#imagePageInfo').textContent=`Đang hiển thị ${images.length} / ${imageTotal}`;$('#loadMoreImages').hidden=images.length>=imageTotal;$('#imageRows').innerHTML=images.length?images.map(x=>`<tr><td><div class="img-cell"><img class="thumb" src="/api/images/${x.id}/file"><div><b>${esc(x.rel_path.split(/[\\/]/).pop())}</b><small>${esc(x.rel_path)}</small></div></div></td><td>${x.width||'—'} × ${x.height||'—'}</td><td>${x.object_count}</td><td><span class="status-pill ${x.status}">${statusLabel(x.status)}</span>${x.error?`<small title="${esc(x.error)}"> ⚠</small>`:''}</td><td><button class="row-action" onclick="openImage(${x.id})">Review →</button></td></tr>`).join(''):'<tr><td colspan="5" class="empty">Không có ảnh phù hợp. Import thư mục để bắt đầu.</td></tr>'}catch(e){toast(e.message,true)}}
function statusLabel(s){return {pending:'Chờ xử lý',processing:'Đang chạy',processed:'Đã xử lý',failed:'Lỗi'}[s]||s}function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function checkModel(){const p=$('#yoloPath').value.trim();$('#modelStatus').textContent='Đang tải checkpoint và đọc model.names…';try{const r=await api('/api/model/check?path='+encodeURIComponent(p)+'&device='+encodeURIComponent($('#deviceSelect').value));$('#modelStatus').textContent=`Hợp lệ · device ${r.device} · classes: ${Object.values(r.names).join(', ')}`;$('#modelStatus').style.color='var(--mint)';toast('Checkpoint YOLO hợp lệ')}catch(e){$('#modelStatus').textContent=e.message;$('#modelStatus').style.color='var(--red)';toast(e.message,true)}}
async function startJob(){const b={yolo_model:$('#yoloPath').value.trim(),device:$('#deviceSelect').value,dino_model:$('#dinoPath').value.trim()||null,sam_model:$('#samPath').value.trim()||null,yolo_conf:Number($('#conf').value),dino_box_threshold:Number($('#dinoBox').value),dino_text_threshold:Number($('#dinoText').value),imgsz:document.querySelector('input[name=mode]:checked').value==='high_accuracy'?1280:(document.querySelector('input[name=mode]:checked').value==='cpu_fast'?640:960),mode:document.querySelector('input[name=mode]:checked').value,match_iou:Number($('#matchIou').value),auto_accept:$('#autoAccept')?.checked||false,accept_yolo_only:$('#acceptYoloOnly')?.checked||false,output_dir:$('#autoSavePath')?.value.trim()||null};try{const r=await api('/api/jobs/start',{method:'POST',body:JSON.stringify(b)});$('#startMessage').textContent=`Job #${r.job_id} đã bắt đầu.`;toast('Auto labeling đang chạy');showView('dashboard');refreshAll()}catch(e){$('#startMessage').textContent=e.message;toast(e.message,true)}}
async function jobAction(a){try{await api('/api/jobs/'+a,{method:'POST'});toast(({pause:'Đã yêu cầu tạm dừng',resume:'Đã tiếp tục job',stop:'Đã yêu cầu dừng an toàn',cancel:'Đã yêu cầu hủy bỏ job'})[a]||'Đã gửi lệnh');refreshAll()}catch(e){toast(e.message,true)}}
async function loadQueue(reset=true){if(reset){queueOffset=0;queue=[]}try{const r=await api(`/api/images?status=all&limit=100&offset=${queueOffset}`);const all=r.items;const added=all.filter(x=>x.status==='processed'||x.status==='failed'||x.object_count>0);queue=reset?added:[...queue,...added];queueOffset+=all.length;queueTotal=r.total;$('#queueCount').textContent=queue.length+' / '+queueTotal+' ảnh';$('#queueMore').hidden=queueOffset>=queueTotal;$('#queueList').innerHTML=queue.length?queue.map(x=>`<div class="queue-item ${currentImage?.id===x.id?'active':''}" onclick="openImage(${x.id})"><img src="/api/images/${x.id}/file"><div><b>${esc(x.rel_path.split(/[\\/]/).pop())}</b><small>${x.object_count} nhãn · ${statusLabel(x.status)}</small></div></div>`).join(''):'<div class="empty">Chạy pipeline hoặc chọn ảnh từ Dataset.</div>'}catch(e){toast(e.message,true)}}
async function openImage(id){try{const d=await api('/api/images/'+id);currentImage=d.image;currentAnnotations=d.annotations.map(a=>({...a,metadata:(()=>{try{return JSON.parse(a.metadata||'{}')}catch{return {}}})(),accepted:Boolean(a.accepted),box:[a.x1,a.y1,a.x2,a.y2]}));selectedAnn=-1;undoStack=[];redoStack=[];imgObj=new Image();imgObj.onload=()=>{setupCanvas();drawCanvas()};imgObj.src='/api/images/'+id+'/file';$('#canvasEmpty').style.display='none';$('#editorFile').textContent=currentImage.rel_path;$('#canvasDimensions').textContent=`${currentImage.width} × ${currentImage.height} · ${currentImage.status}`;showView('review');loadQueue();renderAnnotations()}catch(e){toast(e.message,true)}}
function setupCanvas(){const c=$('#canvas'),stage=$('.canvas-stage');const rect=stage.getBoundingClientRect();c.width=Math.max(1,rect.width*devicePixelRatio);c.height=Math.max(1,rect.height*devicePixelRatio);c.style.width=rect.width+'px';c.style.height=rect.height+'px';canvasScale=Math.min(c.width/imgObj.naturalWidth,c.height/imgObj.naturalHeight);canvasOffset={x:(c.width-imgObj.naturalWidth*canvasScale)/2,y:(c.height-imgObj.naturalHeight*canvasScale)/2}}
function drawCanvas(){
 const c=$('#canvas'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(!imgObj)return;
 ctx.drawImage(imgObj,canvasOffset.x,canvasOffset.y,imgObj.naturalWidth*canvasScale,imgObj.naturalHeight*canvasScale);
 const drawRaw=(det,color,label)=>{if(!det?.box)return;const b=det.box.map((v,j)=>j%2===0?canvasOffset.x+v*canvasScale:canvasOffset.y+v*canvasScale);ctx.save();ctx.lineWidth=1.5*devicePixelRatio;ctx.setLineDash([6*devicePixelRatio,4*devicePixelRatio]);ctx.strokeStyle=color;ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.font=`${9*devicePixelRatio}px system-ui`;const text=`${label} ${det.class_name||'ambiguous'} ${Number(det.score||0).toFixed(2)}`;ctx.fillStyle=color;ctx.fillText(text,b[0]+2*devicePixelRatio,Math.max(canvasOffset.y+10*devicePixelRatio,b[1]-3*devicePixelRatio));ctx.restore()};
 for(const a of currentAnnotations){const meta=a.metadata||{};if(showMasks&&meta.sam?.mask_path){let mask=maskCache[meta.sam.mask_path];if(!mask){mask=new Image();mask.onload=drawCanvas;mask.src='/api/masks/'+encodeURIComponent(meta.sam.mask_path);maskCache[meta.sam.mask_path]=mask}if(mask.complete&&mask.naturalWidth){ctx.globalAlpha=.22;ctx.drawImage(mask,canvasOffset.x,canvasOffset.y,imgObj.naturalWidth*canvasScale,imgObj.naturalHeight*canvasScale);ctx.globalAlpha=1}}
  if(showYolo)drawRaw(meta.yolo,colors.bus,'YOLO');if(showDino)drawRaw(meta.dino,colors.blue,'DINO');
 }
 if(!showFinal)return;
 currentAnnotations.forEach((a,i)=>{const [x1,y1,x2,y2]=a.box.map((v,j)=>j%2===0?canvasOffset.x+v*canvasScale:canvasOffset.y+v*canvasScale),color=a.quality==='high_risk'?'#ff7979':(colors[a.class_name]||'#fff');ctx.lineWidth=(i===selectedAnn?2.7:1.7)*devicePixelRatio;ctx.strokeStyle=color;ctx.fillStyle=color+'24';ctx.fillRect(x1,y1,x2-x1,y2-y1);ctx.strokeRect(x1,y1,x2-x1,y2-y1);const label=`${a.class_name} ${a.score==null?'':Number(a.score).toFixed(2)} · ${a.quality||a.source}`;ctx.font=`${11*devicePixelRatio}px system-ui`;const tw=ctx.measureText(label).width;ctx.fillStyle=color;ctx.fillRect(x1,Math.max(canvasOffset.y,y1-19*devicePixelRatio),tw+9*devicePixelRatio,18*devicePixelRatio);ctx.fillStyle='#09110e';ctx.fillText(label,x1+4*devicePixelRatio,Math.max(canvasOffset.y+13*devicePixelRatio,y1-6*devicePixelRatio));if(i===selectedAnn){ctx.fillStyle='#fff';ctx.fillRect(x2-4*devicePixelRatio,y2-4*devicePixelRatio,8*devicePixelRatio,8*devicePixelRatio)}})
}
function renderAnnotations(){if(!currentImage)return;$('#annCount').textContent=currentAnnotations.length;$('#annotationList').innerHTML=currentAnnotations.length?currentAnnotations.map((a,i)=>`<div class="ann-row ${i===selectedAnn?'sel':''}" onclick="selectAnn(${i})"><i class="ann-swatch" style="background:${colors[a.class_name]||'#fff'}"></i><div><b>${esc(a.class_name)} <small>${a.score==null?'':Number(a.score).toFixed(2)}</small></b><small>${esc(a.source)} · ${esc(a.quality||'human')}</small></div><input type="checkbox" title="Chấp nhận nhãn để export" ${a.accepted?'checked':''} onchange="toggleAccepted(${i},this.checked)" onclick="event.stopPropagation()">${a.metadata?.sam?.mask_derived_box?`<button class="ghost" title="Áp dụng box SAM gợi ý" onclick="event.stopPropagation();applySamBox(${i})">SAM box</button>`:''}<button class="ann-delete" title="Xóa" onclick="event.stopPropagation();deleteAnn(${i})">×</button></div>`).join(''):'<div class="empty">Không có box. Click + để vẽ.</div>';drawCanvas()}
function selectAnn(i){selectedAnn=i;renderAnnotations()}function toggleAccepted(i,value){currentAnnotations[i].accepted=!!value}function saveState(){undoStack.push(JSON.stringify(currentAnnotations));if(undoStack.length>40)undoStack.shift();redoStack=[]}function undo(){if(!undoStack.length)return;redoStack.push(JSON.stringify(currentAnnotations));currentAnnotations=JSON.parse(undoStack.pop());selectedAnn=-1;renderAnnotations()}function redo(){if(!redoStack.length)return;undoStack.push(JSON.stringify(currentAnnotations));currentAnnotations=JSON.parse(redoStack.pop());renderAnnotations()}
function deleteAnn(i){saveState();currentAnnotations.splice(i,1);selectedAnn=-1;renderAnnotations()}function newBox(){if(!currentImage){toast('Chọn ảnh trước',true);return}saveState();const w=currentImage.width,h=currentImage.height;currentAnnotations.push({class_name:'car',class_id:1,source:'manual',quality:'human_reviewed',accepted:1,box:[w*.25,h*.25,w*.5,h*.5],_visible:true});selectedAnn=currentAnnotations.length-1;renderAnnotations()}
function canvasPoint(ev){const r=$('#canvas').getBoundingClientRect();return {x:(ev.clientX-r.left)*devicePixelRatio,y:(ev.clientY-r.top)*devicePixelRatio}}
function pointImage(p){return {x:(p.x-canvasOffset.x)/canvasScale,y:(p.y-canvasOffset.y)/canvasScale}}
const canvas=$('#canvas');canvas.addEventListener('mousedown',ev=>{if(!currentImage)return;if(ev.button===1||spaceDown){ev.preventDefault();const q=canvasPoint(ev);drag={type:'pan',start:q,offset:{...canvasOffset}};return}const p=pointImage(canvasPoint(ev));if(p.x<0||p.y<0||p.x>currentImage.width||p.y>currentImage.height)return;let hit=-1;for(let i=currentAnnotations.length-1;i>=0;i--){const b=currentAnnotations[i].box;if(p.x>=b[0]&&p.x<=b[2]&&p.y>=b[1]&&p.y<=b[3]){hit=i;break}}if(hit>=0){saveState();selectedAnn=hit;const b=currentAnnotations[hit].box;drag={type: p.x>b[2]-14/canvasScale&&p.y>b[3]-14/canvasScale?'resize':'move',start:p,box:[...b]}}else{saveState();currentAnnotations.push({class_name:'car',class_id:1,source:'manual',quality:'human_reviewed',accepted:1,box:[p.x,p.y,p.x,p.y],_visible:true});selectedAnn=currentAnnotations.length-1;drag={type:'draw',start:p,box:[p.x,p.y,p.x,p.y]}}renderAnnotations()});canvas.addEventListener('mousemove',ev=>{if(!drag)return;if(drag.type==='pan'){const q=canvasPoint(ev);canvasOffset={x:drag.offset.x+q.x-drag.start.x,y:drag.offset.y+q.y-drag.start.y};drawCanvas();return}if(selectedAnn<0)return;const p=pointImage(canvasPoint(ev)),a=currentAnnotations[selectedAnn],dx=p.x-drag.start.x,dy=p.y-drag.start.y;if(drag.type==='draw')a.box=[drag.start.x,drag.start.y,p.x,p.y];if(drag.type==='resize')a.box=[drag.box[0],drag.box[1],p.x,p.y];if(drag.type==='move')a.box=[drag.box[0]+dx,drag.box[1]+dy,drag.box[2]+dx,drag.box[3]+dy];a.box[0]=Math.max(0,Math.min(currentImage.width-1,a.box[0]));a.box[1]=Math.max(0,Math.min(currentImage.height-1,a.box[1]));a.box[2]=Math.max(a.box[0]+1,Math.min(currentImage.width,a.box[2]));a.box[3]=Math.max(a.box[1]+1,Math.min(currentImage.height,a.box[3]));drawCanvas()});window.addEventListener('mouseup',()=>{if(drag){const wasPan=drag.type==='pan';drag=null;if(!wasPan)renderAnnotations()}});canvas.addEventListener('contextmenu',e=>e.preventDefault());canvas.addEventListener('wheel',e=>{if(!currentImage)return;e.preventDefault();const p=canvasPoint(e),anchor=pointImage(p);canvasScale=Math.max(.02,Math.min(20,canvasScale*(e.deltaY<0?1.12:.89)));canvasOffset={x:p.x-anchor.x*canvasScale,y:p.y-anchor.y*canvasScale};drawCanvas()},{passive:false});
function assignClass(c){if(selectedAnn<0)return;saveState();currentAnnotations[selectedAnn].class_name=c;currentAnnotations[selectedAnn].class_id=classNames.indexOf(c);currentAnnotations[selectedAnn].source='manual';currentAnnotations[selectedAnn].accepted=1;renderAnnotations()}
function toggleMasks(){showMasks=!showMasks;$('#maskToggle').textContent='SAM masks: '+(showMasks?'on':'off');drawCanvas()}function toggleLayer(name){if(name==='yolo')showYolo=!showYolo;if(name==='dino')showDino=!showDino;if(name==='final')showFinal=!showFinal;$('#yoloToggle').textContent='YOLO: '+(showYolo?'on':'off');$('#dinoToggle').textContent='DINO: '+(showDino?'on':'off');$('#finalToggle').textContent='Final labels: '+(showFinal?'on':'off');drawCanvas()}function applySamBox(i){const a=currentAnnotations[i],b=a.metadata?.sam?.mask_derived_box;if(!b)return;saveState();a.metadata.previous_box=[...a.box];a.metadata.sam.refinement_applied_at=new Date().toISOString();a.box=[...b];a.source='manual';a.accepted=false;selectedAnn=i;renderAnnotations();toast('Đã áp dụng box SAM gợi ý; kiểm tra lại trước khi chấp nhận')}
async function saveReview(){if(!currentImage)return;try{const payload=currentAnnotations.map(a=>({id:a.id||null,class_name:a.class_name,box:a.box,accepted:Boolean(a.accepted),metadata:a.metadata||{}}));await api(`/api/images/${currentImage.id}/review`,{method:'PUT',body:JSON.stringify({annotations:payload})});toast('Đã lưu annotation và lịch sử review');openImage(currentImage.id);refreshAll()}catch(e){toast(e.message,true)}}
function findQueueIndex(){return queue.findIndex(x=>x.id===currentImage?.id)}function nextImage(){const i=findQueueIndex();if(i>=0&&queue[i+1])openImage(queue[i+1].id)}function prevImage(){const i=findQueueIndex();if(i>0)openImage(queue[i-1].id)}function fitCanvas(){if(imgObj){setupCanvas();drawCanvas()}}
window.addEventListener('keyup',e=>{if(e.code==='Space')spaceDown=false});window.addEventListener('blur',()=>{spaceDown=false});window.addEventListener('resize',()=>{if(currentView==='review'&&imgObj)fitCanvas()});window.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){spaceDown=true;e.preventDefault();return}if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName))return;const key=e.key.toLowerCase();if(e.ctrlKey&&key==='s'){e.preventDefault();saveReview();return}if(e.ctrlKey&&key==='z'){e.preventDefault();undo();return}if(e.ctrlKey&&key==='y'){e.preventDefault();redo();return}if(key==='delete'||key==='backspace'){if(selectedAnn>=0)deleteAnn(selectedAnn);return}if(key==='arrowright'){nextImage();return}if(key==='arrowleft'){prevImage();return}if(['1','2','3','4','5'].includes(key))assignClass(classNames[Number(key)-1])});
async function exportData(){try{const r=await api('/api/export',{method:'POST',body:JSON.stringify({name:$('#exportName').value.trim(),output_dir:$('#customExportPath')?.value.trim()||null})});$('#exportResult').textContent=`Export completo: ${r.images} ảnh · ${r.path} · data.yaml: ${r.data_yaml}`;toast('Đã tạo dataset snapshot')}catch(e){$('#exportResult').textContent=e.message;toast(e.message,true)}}
async function loadQueueFirst(){await loadQueue();if(queue.length)openImage(queue[0].id)}
['yoloPath','dinoPath','samPath'].forEach(id=>$('#'+id)?.addEventListener('input',e=>e.target.dataset.touched='1'));refreshAll();loadImages();pollTimer=setInterval(refreshAll,2500);

const trafficNames=['Thong_thoang','Dong_xe','Un_u_nhe','Un_tac_nang'];
async function loadCameras(){try{const rows=await api('/api/cameras');if(rows.length&&!$('#cameraId').value)$('#cameraId').value=rows[0].camera_id}catch(e){toast(e.message,true)}}
async function loadCameraConfig(){try{const cam=$('#cameraId').value.trim(),cfg=await api('/api/cameras/'+encodeURIComponent(cam)+'/roi');$('#cameraConfig').value=JSON.stringify(cfg,null,2);toast('Đã tải cấu hình '+cam)}catch(e){toast(e.message,true)}}
async function saveCameraConfig(){try{const cam=$('#cameraId').value.trim(),config=JSON.parse($('#cameraConfig').value);await api('/api/cameras/'+encodeURIComponent(cam)+'/roi',{method:'PUT',body:JSON.stringify({config})});toast('Đã lưu ROI và hiệu chuẩn camera');loadCameras()}catch(e){toast(e.message,true)}}
async function runTrafficAnalysis(){const b=$('#trafficRows');b.innerHTML='<tr><td colspan="5" class="empty">Đang tính đặc trưng…</td></tr>';try{const r=await api('/api/traffic/analyze',{method:'POST'});$('#trafficMessage').textContent=`Đã phân tích ${r.processed} ảnh · ${r.labeled} nhãn provisional · ${r.needs_review} cần review. Occupancy đo từ box area là proxy, mask occupancy chưa có.`;toast('Phân tích hoàn tất');await loadTraffic()}catch(e){$('#trafficMessage').textContent=e.message;toast(e.message,true)}}
async function loadTraffic(){try{const r=await api('/api/traffic/labels?limit=500');$('#trafficRows').innerHTML=r.items.length?r.items.map(row=>{const f=row.features||JSON.parse(row.features_json||'{}'),val=f.predicted_traffic_class||'',opts='<option value="">Chưa đề xuất</option>'+trafficNames.map(n=>`<option value="${n}" ${n===val?'selected':''}>${n}</option>`).join('');return `<tr><td><b>${esc(row.rel_path||'')}</b><small>${esc(f.camera_id||row.camera_id||'')}</small></td><td>${f.total_vehicle_count??'—'} ${f.uncertain_vehicle_count?`(+${f.uncertain_vehicle_count} chưa rõ)`:' '}</td><td>${f.box_occupancy_proxy==null?'—':(100*f.box_occupancy_proxy).toFixed(1)+'%'} <small>${esc(f.occupancy_source||'')}</small></td><td><select id="trafficLabel${row.image_id}">${opts}</select></td><td>${esc(f.review_status||row.review_status)}<small>${esc((f.reasons||[]).join(', '))}</small><button class="row-action" onclick="saveTrafficLabel(${row.image_id})">Xác nhận nhãn</button></td></tr>`}).join(''):'<tr><td colspan="5" class="empty">Chưa có kết quả. Nhập dataset và chạy Detection trước.</td></tr>'}catch(e){toast(e.message,true)}}
async function saveTrafficLabel(id){try{const label=$('#trafficLabel'+id).value;if(!label)throw Error('Chọn một nhãn giao thông');await api('/api/traffic/labels/'+id,{method:'PUT',body:JSON.stringify({label,accepted:true})});toast('Đã lưu nhãn con người xác minh');loadTraffic()}catch(e){toast(e.message,true)}}
async function exportTraffic(){try{const r=await api('/api/traffic/export',{method:'POST',body:JSON.stringify({name:'traffic_features',mode:'extended'})});$('#trafficMessage').textContent=`Đã xuất ${r.records} bản ghi extended: ${r.path}. Không tương thích legacy 46-feature.`;toast('Đã xuất extended CSV')}catch(e){$('#trafficMessage').textContent=e.message;toast(e.message,true)}}

async function exportClassification(){try{const r=await api('/api/traffic/export-classification',{method:'POST',body:JSON.stringify({name:'traffic_classification',include_pseudo:false})});$('#trafficMessage').textContent=`Đã xuất ${r.images} ảnh đã xác minh: ${r.path} · train ${r.train} / val ${r.val} · split ${r.split_method}.`;toast('Đã xuất classification dataset')}catch(e){$('#trafficMessage').textContent=e.message;toast(e.message,true)}}
