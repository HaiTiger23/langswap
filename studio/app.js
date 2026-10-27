const $=id=>document.getElementById(id);
let selected=null, objectUrl=null, currentJob=sessionStorage.getItem('long-watch-job'), timer=null, polling=false, jobsSnapshot=null, queueFilter='all', submitting=false, savedVoices=[], serviceWorkerRegistration=null, notificationStates=new Map(), notificationsPrimed=false;
const names=['Tách âm thanh','Tách lời Trung khỏi nền','Nhận diện lời thoại','Dịch sang tiếng Việt','Tạo giọng OmniVoice','Căn giọng và ghép video'];
const DUB_SETTINGS_KEY='long-dub-settings-v1';
function readDubSettings(){try{return JSON.parse(localStorage.getItem(DUB_SETTINGS_KEY)||'{}')||{}}catch{return {}}}
const savedDubSettings=readDubSettings();
let preferredVoiceId=typeof savedDubSettings.voice_id==='string'?savedDubSettings.voice_id:'';
function saveDubSettings(){
 const settings={quality:$('quality').value,duck_db:$('duck').value,text_mode:$('screenText').value,voice_id:$('savedVoice').value,settings_open:$('quickSettings').open,updated_at:Date.now()};
 try{localStorage.setItem(DUB_SETTINGS_KEY,JSON.stringify(settings))}catch{}
}
const viewCopy={
 create:{eyebrow:'TẠO BẢN LỒNG MỚI',title:'Bắt đầu với<br class="mobile-break"> video của bạn<span>.</span>',intro:'Chọn video, tinh chỉnh khi cần, rồi đưa vào hàng đợi.'},
 process:{eyebrow:'THEO DÕI XỬ LÝ',title:'Video đang được<br class="mobile-break"> dựng<span>.</span>',intro:'Mọi bước, thời gian và bản thành phẩm ở cùng một nơi.'},
 queue:{eyebrow:'THƯ VIỆN CỦA BẠN',title:'Hàng đợi &<br class="mobile-break"> video đã làm<span>.</span>',intro:'Mở lại, tải xuống hoặc chạy lại bất cứ video nào.'}
};
function setView(view,{scroll=true}={}){
 if(!viewCopy[view])return;
 document.body.dataset.view=view;
 document.querySelectorAll('.app-view').forEach(panel=>panel.classList.toggle('active',panel.dataset.view===view));
 document.querySelectorAll('[data-nav]').forEach(button=>button.classList.toggle('active',button.dataset.nav===view));
 const copy=viewCopy[view];$('pageEyebrow').textContent=copy.eyebrow;$('pageTitle').innerHTML=copy.title;$('pageIntro').textContent=copy.intro;
 try{localStorage.setItem('long-active-view',view)}catch{}
 if(scroll)window.scrollTo({top:0,behavior:'smooth'});
}
try{setView(localStorage.getItem('long-active-view')||'create',{scroll:false})}catch{setView('create',{scroll:false})}
document.querySelectorAll('[data-nav]').forEach(button=>button.onclick=()=>setView(button.dataset.nav));
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(timer);timer=setTimeout(()=>$('toast').hidden=true,6000)}
function submissionId(){
 if(globalThis.crypto?.randomUUID)return globalThis.crypto.randomUUID();
 if(globalThis.crypto?.getRandomValues){const bytes=new Uint32Array(4);globalThis.crypto.getRandomValues(bytes);return [...bytes].map(value=>value.toString(16)).join('')}
 return Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
}
function selectFile(file){
 if(!file)return;
 if(file.size>256*1024*1024){toast('Video cần nhỏ hơn 256 MB.');return}
 selected=file;if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=URL.createObjectURL(file);
 $('sourceVideo').src=objectUrl;$('sourcePreview').hidden=false;$('dropzone').hidden=true;$('fileName').textContent=file.name;
 $('fileMeta').textContent=(file.size/1024/1024).toFixed(1)+' MB';$('start').disabled=false;
 $('sourceVideo').onloadedmetadata=()=>{const d=$('sourceVideo').duration;$('fileMeta').textContent=(file.size/1024/1024).toFixed(1)+' MB · '+Math.floor(d/60)+':'+String(Math.floor(d%60)).padStart(2,'');if(d>300){toast('Video dài tối đa 5 phút. Hãy chọn một video ngắn hơn.');$('start').disabled=true}};
}
function clearVideo(){
 selected=null;if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=null;$('videoFile').value='';
 $('sourceVideo').pause();$('sourceVideo').removeAttribute('src');$('sourcePreview').hidden=true;$('dropzone').hidden=false;$('start').disabled=true;
}
$('videoFile').onchange=e=>selectFile(e.target.files[0]);
$('changeFile').onclick=()=>{$('videoFile').value='';$('videoFile').click()};$('removeFile').onclick=clearVideo;
$('dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('videoFile').click()}};
['dragenter','dragover'].forEach(name=>$('dropzone').addEventListener(name,e=>{e.preventDefault();$('dropzone').classList.add('dragging')}));
['dragleave','drop'].forEach(name=>$('dropzone').addEventListener(name,e=>{e.preventDefault();$('dropzone').classList.remove('dragging')}));
$('dropzone').addEventListener('drop',e=>selectFile(e.dataTransfer.files[0]));
$('quality').value=savedDubSettings.quality==='32'?'32':'16';
$('duck').value=String(Math.min(18,Math.max(0,Number(savedDubSettings.duck_db)||9)));
function updateDuckValue(){ $('duckValue').textContent='−'+$('duck').value+' dB' }
$('duck').oninput=()=>{updateDuckValue();saveDubSettings()};updateDuckValue();
const screenTextDescriptions={
 off:'Giữ nguyên chữ trên hình, chỉ lồng tiếng Việt.',
 subtitles:'Che phụ đề Trung; giữ nguyên các nhãn và chữ khác trên hình.',
 all:'Che phụ đề Trung và thay các nhãn bằng tiếng Việt. Giữ màu, viền gần kiểu gốc; cố định cỡ chữ và vị trí, không dùng ô nền lớn.',
 all_subtitles:'Thay cả phụ đề lời thoại và các nhãn bằng tiếng Việt. Mỗi dòng được dịch ngắn theo ngữ cảnh để vừa vị trí chữ gốc.'
};
if(Object.hasOwn(screenTextDescriptions,savedDubSettings.text_mode))$('screenText').value=savedDubSettings.text_mode;
function updateScreenTextSetting(){
 const mode=$('screenText').value;$('screenTextNote').textContent=screenTextDescriptions[mode];$('screenTextNote').classList.toggle('enabled',mode!=='off');
 saveDubSettings();
}
$('screenText').onchange=updateScreenTextSetting;updateScreenTextSetting();
$('quality').onchange=saveDubSettings;
$('quickSettings').open=!!savedDubSettings.settings_open;
$('quickSettings').ontoggle=saveDubSettings;

function setUploadProgress(value,label){
 const shown=Math.max(0,Math.min(100,Math.round(value)));$('uploadProgress').hidden=false;$('uploadLabel').textContent=label;$('uploadPercent').textContent=shown+'%';$('uploadBar').style.width=shown+'%';
}
function hideUploadProgress(){$('uploadProgress').hidden=true}
function busy(value){
 submitting=value;$('start').disabled=value||!selected;$('start').classList.toggle('loading',value);$('start').querySelector('span').textContent=value?'Đang tải lên…':'Thêm vào hàng đợi';
 ['changeFile','removeFile','videoFile','reference','referenceText','savedVoice','saveVoice','voiceName'].forEach(id=>$(id).disabled=value||($(id).dataset.voiceLocked==='true'));
}

function updateVoiceControls(){
 const usingSaved=!!$('savedVoice').value;
 for(const id of ['reference','referenceText','saveVoice','voiceName'])$(id).dataset.voiceLocked=usingSaved?'true':'';
 $('reference').disabled=usingSaved||submitting;$('referenceText').disabled=usingSaved||submitting;$('saveVoice').disabled=usingSaved||submitting;
 $('voiceName').disabled=usingSaved||!$('saveVoice').checked||submitting;
 $('voiceHint').textContent=usingSaved?'Giọng đã lưu sẽ được dùng cho mọi câu trong video này. Chọn “Tạo giọng tự động” để dùng mẫu mới.':'Bỏ trống để hệ thống tự tạo một giọng Việt xuyên suốt. Mẫu giọng đã lưu chỉ nằm trên máy này.';
}
function renderVoices(){
 const select=$('savedVoice'),chosen=select.value||preferredVoiceId;select.replaceChildren();select.append(new Option('Tạo giọng tự động',''));
 for(const voice of savedVoices)select.append(new Option(voice.name,voice.id));
 if(savedVoices.some(voice=>voice.id===chosen))select.value=chosen;else preferredVoiceId='';updateVoiceControls();saveDubSettings();
}
async function loadVoices(){try{const data=await request('/api/voices');savedVoices=data.voices||[];renderVoices()}catch{}}
$('savedVoice').onchange=()=>{preferredVoiceId=$('savedVoice').value;updateVoiceControls();saveDubSettings()};
$('reference').onchange=()=>{if($('reference').files[0]&&$('savedVoice').value){$('savedVoice').value='';preferredVoiceId='';updateVoiceControls();saveDubSettings()}};
$('saveVoice').onchange=updateVoiceControls;
async function saveCurrentVoice(){
 const reference=$('reference').files[0],referenceText=$('referenceText').value.trim(),name=$('voiceName').value.trim();
 if(!reference){throw Error('Chọn file mẫu giọng trước khi lưu.')}
 if(!referenceText){throw Error('Nhập đúng lời nói trong mẫu giọng trước khi lưu.')}
 if(!name){throw Error('Đặt tên cho giọng để dễ chọn ở lần sau.')}
 const form=new FormData();form.append('reference',reference);form.append('reference_text',referenceText);form.append('name',name);
 const voice=await upload('/api/voices',form,(percent)=>setUploadProgress(percent,'Đang lưu mẫu giọng…'));
 savedVoices=[voice,...savedVoices.filter(item=>item.id!==voice.id)];renderVoices();$('savedVoice').value=voice.id;preferredVoiceId=voice.id;$('saveVoice').checked=false;$('voiceName').value='';updateVoiceControls();saveDubSettings();return voice.id;
}

function setSteps(stage,done=false){document.querySelectorAll('[data-step]').forEach((node,i)=>{node.classList.toggle('done',done||i<stage);node.classList.toggle('active',!done&&i===stage);node.firstElementChild.textContent=done||i<stage?'✓':i+1})}
function resetResult(){
 $('resultVideo').pause();$('resultVideo').removeAttribute('src');$('resultVideo').hidden=true;$('emptyResult').hidden=false;$('previewStage').classList.remove('has-video');$('extras').hidden=true;$('downloadVideo').classList.add('disabled');$('downloadVideo').removeAttribute('href');$('downloadVideo').setAttribute('aria-disabled','true');$('downloadLog').hidden=true;
}
function showResult(job){
 const f=job.files;if($('resultVideo').getAttribute('src')!==f.video)$('resultVideo').src=f.video;$('resultVideo').hidden=false;$('emptyResult').hidden=true;$('previewStage').classList.add('has-video');$('downloadVideo').href=f.video;$('downloadVideo').download='video_tieng_viet.mp4';$('downloadVideo').classList.remove('disabled');$('downloadVideo').setAttribute('aria-disabled','false');
 $('extras').hidden=false;$('downloadAudio').href=f.audio;$('downloadSrt').href=f.srt;$('downloadAudio').download='am_thanh_tieng_viet.wav';$('downloadLog').href=f.log;$('downloadLog').hidden=false;$('resultNote').textContent='MP4 · Giữ độ phân giải gốc';
}
function render(job){
 currentJob=job.id;
 const state=job.status;const running=state==='running'||state==='queued';
 $('viewingName').hidden=false;$('viewingName').textContent=job.name;$('viewingName').title=job.name;
 $('statusBadge').className='status-pill '+(state==='done'?'done':state==='error'?'error':'running');$('statusBadge').textContent={running:'Đang xử lý',queued:'Chờ #'+(job.queue_position||'…'),done:'Hoàn tất',error:'Có lỗi',cancelled:'Đã hủy'}[state]||state;
 $('processDot').hidden=!running;
 $('liveMessage').textContent=job.message||'';$('liveMessage').classList.toggle('error',state==='error');$('logs').textContent=(job.history||[]).join('\n')||job.message;
 const match=(job.message||'').match(/([1-6])\/6/);let stage=match?Number(match[1])-1:Math.min(5,Math.floor((job.progress||0)*6));
 if(job.message?.includes('OmniVoice'))stage=4;
 setSteps(stage,state==='done');
 $('progressTitle').textContent=state==='done'?'Video tiếng Việt đã sẵn sàng':state==='error'?'Chưa thể hoàn tất video':state==='queued'?'Đang chờ · vị trí '+(job.queue_position||'…'):`Bước ${stage+1}/6 · ${names[stage]}`;
 const elapsed=Math.max(0,Math.floor((job.finished||Date.now()/1000)-(job.started||job.created)));
 $('elapsed').textContent=Math.floor(elapsed/60)+'p '+String(elapsed%60).padStart(2,'0')+'s';
 if(state==='done'){showResult(job);sessionStorage.setItem('long-watch-job',job.id)}
 if(state==='error'){sessionStorage.setItem('long-watch-job',job.id);if(job.files?.video){showResult(job);$('statusBadge').textContent='Cần kiểm tra';$('progressTitle').textContent='Đã có bản xuất · Cần kiểm tra';$('resultNote').textContent='Bản xuất gần nhất · Kiểm tra chưa đạt'}else{resetResult();$('resultNote').textContent='Xem nhật ký để biết thêm chi tiết'}}
 return running;
}
async function request(url,options){const r=await fetch(url,options);if(!r.ok){let msg='Không thể kết nối với ứng dụng.';try{const b=await r.json();msg=typeof b.detail==='string'?b.detail:msg}catch{}throw Error(msg)}return r.json()}
function upload(url,form,onProgress){
 return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();xhr.open('POST',url);xhr.responseType='json';
  xhr.upload.onprogress=event=>{if(event.lengthComputable)onProgress(event.loaded/event.total*100)};
  xhr.onerror=()=>reject(Error('Mất kết nối trong lúc tải file lên.'));
  xhr.onload=()=>{const body=xhr.response||{};if(xhr.status>=200&&xhr.status<300)resolve(body);else reject(Error(typeof body.detail==='string'?body.detail:'Không thể tải file lên.'))};xhr.send(form);
 })
}
$('start').onclick=async()=>{
 if(!selected||submitting)return;
 saveDubSettings();
 let ref=$('reference').files[0],voiceId=$('savedVoice').value,refText=$('referenceText').value.trim();
 if(ref&&!refText){toast('Nhập đúng lời nói trong mẫu giọng, hoặc bỏ mẫu để dùng giọng tự động.');$('referenceText').focus();return}
 if($('saveVoice').checked&&!ref){toast('Chọn file mẫu giọng trước khi lưu.');$('reference').focus();return}
 busy(true);resetResult();setSteps(0);$('statusBadge').textContent='Đang tải lên';$('statusBadge').className='status-pill running';$('liveMessage').textContent='Đang đưa video vào hàng đợi xử lý…';setUploadProgress(0,'Đang chuẩn bị tải video…');
 try{
  if($('saveVoice').checked){voiceId=await saveCurrentVoice();ref=null;refText=''}
  const form=new FormData();form.append('video',selected);form.append('submission_id',submissionId());form.append('reference_text',refText);form.append('voice_id',voiceId);form.append('duck_db',$('duck').value);form.append('steps',$('quality').value);form.append('text_mode',$('screenText').value);if(ref)form.append('reference',ref);
  const job=await upload('/api/jobs',form,percent=>setUploadProgress(percent,'Đang tải video lên…'));
  setUploadProgress(100,'Video đã tải lên — đang thêm vào hàng đợi…');currentJob=job.id;sessionStorage.setItem('long-watch-job',job.id);watch(job);setView('process');toast(job.reused?'Lượt gửi này đã được nhận trước đó. Mở lại đúng tác vụ để theo dõi.':'Đã thêm một lượt chạy mới vào hàng đợi.');await refreshQueue();setTimeout(hideUploadProgress,900);
 }catch(e){$('statusBadge').textContent='Chưa thể bắt đầu';$('statusBadge').className='status-pill error';$('liveMessage').textContent=e.message;toast(e.message);hideUploadProgress()}finally{busy(false)}
};

function node(tag,className,text){const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n}
function watch(job){if(currentJob!==job.id)resetResult();currentJob=job.id;sessionStorage.setItem('long-watch-job',job.id);render(job)}
function queueRows(data){
 const list=$('queueList');list.replaceChildren();
 let jobs=data.jobs.filter(j=>queueFilter==='all'||(queueFilter==='active'?['running','queued'].includes(j.status):queueFilter==='error'?['error','cancelled'].includes(j.status):j.status===queueFilter));
 const priority={running:0,queued:1,done:2,error:3,cancelled:4};
 jobs.sort((a,b)=>priority[a.status]-priority[b.status]||(a.queue_position||0)-(b.queue_position||0)||b.created-a.created);
 if(!jobs.length){list.append(node('p','queue-empty','Chưa có tác vụ trong mục này.'));return}
 for(const j of jobs){
  const row=node('div','queue-row'+(j.id===currentJob?' watching':''));const name=node('div','queue-name');name.append(node('strong','',j.name));name.title=j.name;
  name.append(node('small','',new Date(j.created*1000).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+' · #'+j.id.slice(0,7)));
  const label={running:j.cancel_requested?'Đang dừng…':'Đang xử lý',queued:'Chờ #'+j.queue_position,done:'Hoàn tất',error:j.files?.video?'Cần kiểm tra':'Có lỗi',cancelled:'Đã hủy'}[j.status];
  const state=node('span','queue-state '+j.status,label);const progress=node('div','queue-progress',(j.message||'').replace(/^\[.*?\] /,''));progress.title=j.message||'';
  const track=node('div');const bar=node('i');bar.style.width=Math.max(0,Math.min(100,j.progress*100))+'%';track.append(bar);progress.append(track);
  const actions=node('div','queue-row-actions');const view=node('button','',j.files?.video?'Xem video':'Theo dõi');view.onclick=()=>{watch(j);setView('process');queueRows(jobsSnapshot)};actions.append(view);
  if(j.status==='done'){const again=node('button','','Chạy lại');again.onclick=()=>jobAction(j.id,'rerun');actions.append(again);const screen=node('button','','Xử lý chữ');screen.title='Áp dụng lựa chọn Chữ Trung trên hình; dùng lại âm thanh đã lưu';screen.onclick=()=>jobAction(j.id,'screen');actions.append(screen)}
  if(['running','queued'].includes(j.status)){const cancel=node('button','danger','Hủy');cancel.disabled=!!j.cancel_requested;cancel.onclick=()=>jobAction(j.id,'cancel');actions.append(cancel)}
  if(['error','cancelled'].includes(j.status)){const retry=node('button','','Chạy lại');retry.onclick=()=>jobAction(j.id,'retry');actions.append(retry)}
  row.append(name,state,progress,actions);list.append(row);
 }
}
async function jobAction(id,action){if(action==='screen'&&$('screenText').value==='off'){toast('Chọn cách xử lý ở mục Chữ Trung trên hình trước.');$('screenText').scrollIntoView({behavior:'smooth',block:'center'});$('screenText').focus();return}try{const options={method:'POST'};if(action==='screen'){const form=new FormData();form.append('text_mode',$('screenText').value);options.body=form}const job=await request('/api/jobs/'+id+'/'+action,options);if(action==='retry'||action==='rerun'||action==='screen')watch(job);await refreshQueue()}catch(e){toast(e.message)}}
async function refreshQueue(){
 if(polling)return;polling=true;
 try{const data=await request('/api/jobs');jobsSnapshot=data;observeNotifications(data.jobs);
  const c=data.counts;$('queueSummary').textContent=`${c.running} đang chạy · ${c.queued} đang chờ · ${c.done} đã xong`+(data.paused?' · Hàng đợi đang tạm dừng':'');
  $('pauseQueue').textContent=data.paused?'Tiếp tục hàng đợi':'Tạm dừng hàng đợi';
  let job=data.jobs.find(j=>j.id===currentJob);
  if(!job){job=data.jobs.find(j=>j.status==='running')||data.jobs.find(j=>j.status==='queued')||data.jobs.find(j=>j.status==='done');if(job)watch(job)}
  else render(job);
  queueRows(data);
 }catch(e){$('queueSummary').textContent='Đang kết nối lại hàng đợi…'}finally{polling=false}
}
$('pauseQueue').onclick=async()=>{if(!jobsSnapshot)return;const body=new FormData();body.append('paused',!jobsSnapshot.paused);try{await request('/api/queue/pause',{method:'POST',body});await refreshQueue();toast(jobsSnapshot.paused?'Đã tạm dừng. Video đang xử lý vẫn được hoàn tất.':'Hàng đợi đã tiếp tục.')}catch(e){toast(e.message)}};
function openQueue(){setView('queue')}
$('history').onclick=openQueue;$('historyIcon').onclick=openQueue;
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{queueFilter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(n=>n.classList.toggle('selected',n===b));if(jobsSnapshot)queueRows(jobsSnapshot)});
function isAppleMobile(){return /iphone|ipad|ipod/i.test(navigator.userAgent)}
function isStandalone(){return window.matchMedia('(display-mode: standalone)').matches||navigator.standalone===true}
function notificationBlockReason(){
 if(!('Notification' in window))return 'Trình duyệt này chưa hỗ trợ thông báo.';
 if(!window.isSecureContext)return 'Thông báo PWA trên điện thoại cần URL HTTPS. Địa chỉ http://IP-Wi‑Fi:7860 hiện chưa đủ an toàn.';
 if(isAppleMobile()&&!isStandalone())return 'Trên iPhone/iPad, hãy cài Lồng Studio vào Màn hình chính rồi mở từ biểu tượng đó trước khi bật thông báo.';
 if(Notification.permission==='denied')return 'Safari đã chặn quyền. Vào Cài đặt → Thông báo → Lồng Studio, bật “Cho phép thông báo”; nếu chưa thấy app, xóa app khỏi Màn hình chính rồi cài lại từ Safari.';
 return '';
}
function updateNotificationButton(){
 const button=$('notifyButton');if(!('Notification' in window)){button.hidden=true;return}
 const reason=notificationBlockReason(),permission=Notification.permission;
 button.textContent=permission==='granted'?'Thông báo đã bật':reason?'Xem thông báo':'Bật thông báo';button.disabled=false;button.title=reason||'Nhận báo khi video xử lý xong hoặc gặp lỗi khi app đang mở.';
}
async function enableNotifications(){
 const blocked=notificationBlockReason();if(blocked){toast(blocked);return}
 const permission=await Notification.requestPermission();updateNotificationButton();
 if(permission==='granted')toast('Đã bật báo hoàn tất khi app còn mở. Báo nền khi đóng app cần Web Push qua HTTPS, chưa thể dùng trên URL Wi‑Fi HTTP.');else if(permission==='denied')toast(notificationBlockReason());
}
async function setupPwa(){
 updateNotificationButton();$('notifyButton').onclick=enableNotifications;
 let installPrompt=null;const install=$('installButton');
 window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;install.hidden=false});
 install.onclick=async()=>{
  if(installPrompt){installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;install.hidden=true;return}
  toast('Trên iPhone/iPad: mở menu Chia sẻ của Safari → “Thêm vào Màn hình chính”. Trên Android: mở menu trình duyệt → “Cài đặt ứng dụng”.');
 };
 if(/iphone|ipad|ipod/i.test(navigator.userAgent)&&!window.matchMedia('(display-mode: standalone)').matches)install.hidden=false;
 if('serviceWorker' in navigator){try{serviceWorkerRegistration=await navigator.serviceWorker.register('/sw.js');await navigator.serviceWorker.ready}catch{}}
}
function completeNotification(job){
 if(!('Notification' in window)||Notification.permission!=='granted')return;
 const failed=job.status==='error';const title=failed?'Lồng Studio · Xử lý chưa xong':'Lồng Studio · Video đã xong';const body=failed?`${job.name}: ${job.message||'Mở app để xem lỗi.'}`:`${job.name} đã sẵn sàng để xem và tải về.`;
 if(serviceWorkerRegistration?.active)serviceWorkerRegistration.active.postMessage({type:'JOB_COMPLETE',title,body,jobId:job.id});else new Notification(title,{body,tag:'long-job-'+job.id});
}
function observeNotifications(jobs){
 if(!notificationsPrimed){for(const job of jobs)notificationStates.set(job.id,job.status);notificationsPrimed=true;return}
 for(const job of jobs){const previous=notificationStates.get(job.id);if(previous&&previous!==job.status&&['done','error'].includes(job.status))completeNotification(job);notificationStates.set(job.id,job.status)}
}
async function tick(){await refreshQueue();setTimeout(tick,1200)}loadVoices();setupPwa();tick();
