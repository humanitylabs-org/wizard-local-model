(function(){
'use strict';
var $=function(id){return document.getElementById(id);};
var form=$('form'),sel=$('model'),url=$('url'),st=$('status');
var dirty=false,saving=false,catKey='';
function mode(){var r=form.querySelector('input[name=mode]:checked');return r?r.value:'on-box';}
function toggleUrl(){var remote=mode()==='another-machine';$('urlField').hidden=!remote;$('modelField').hidden=remote;}
function fmt(b){b=+b||0;if(b>=1e9)return (b/1e9).toFixed(2)+' GB';if(b>=1e6)return (b/1e6).toFixed(0)+' MB';if(b>=1e3)return (b/1e3).toFixed(0)+' KB';return b+' B';}
function setStatus(t,s){st.textContent=t;st.dataset.state=s;}
function fillCatalog(cat,want){var key=cat.map(function(c){return c.id+c.size;}).join('|');if(key!==catKey){catKey=key;var cur=sel.value;while(sel.firstChild)sel.removeChild(sel.firstChild);cat.forEach(function(c){var o=document.createElement('option');o.value=c.id;o.textContent=c.label+(c.size?' ('+fmt(c.size)+')':'');sel.appendChild(o);});if(cur)sel.value=cur;}if(want!==undefined){sel.value=want;if(sel.value!==want)sel.value='qwen2.5-1.5b';if(!sel.value&&sel.options.length)sel.selectedIndex=0;}}
function applyForm(s){fillCatalog(s.catalog||[],s.model||'qwen2.5-1.5b');form.querySelectorAll('input[name=mode]').forEach(function(r){r.checked=r.value===(s.mode||'on-box');});url.value=s.base_url||'';toggleUrl();}
function render(s){var d=s.download||{},rec=d.received||0,tot=d.total||0;
if(s.status==='connected')setStatus('Model ready','ready');
else if(s.mode==='another-machine')setStatus('Offline: machine not reachable','offline');
else if(d.state==='downloading')setStatus('Downloading model','downloading');
else if(d.state==='failed')setStatus('Download failed','failed');
else setStatus('Loading model','loading');
var show=s.mode==='on-box'&&(d.state==='downloading'||d.state==='failed');$('dl').hidden=!show;
var bar=$('bar');if(tot>0){bar.max=tot;bar.value=Math.min(rec,tot);}else{bar.removeAttribute('value');}
$('count').textContent=d.state==='failed'?'Download stopped at '+fmt(rec)+(tot?' of '+fmt(tot):'')+'.':(tot?fmt(rec)+' of '+fmt(tot)+' ('+Math.floor(rec*100/tot)+'%)':fmt(rec)+' received');
$('retry').hidden=d.state!=='failed';}
function poll(){if(saving){return setTimeout(poll,2000);}fetch('/api/status',{cache:'no-store',headers:{'X-Wizard-Request':'1'}}).then(function(r){if(!r.ok)throw 0;return r.json();}).then(function(s){if(dirty)fillCatalog(s.catalog||[]);else applyForm(s);render(s);}).catch(function(){setStatus('Offline: cannot reach Wizard','offline');}).then(function(){setTimeout(poll,2000);});}
function lock(b){form.querySelectorAll('input[name=mode]').forEach(function(r){r.disabled=b;});sel.disabled=b;url.disabled=b;}
function busy(b){saving=b;lock(b);$('save').disabled=b;$('retry').disabled=b;$('save').textContent=b?'Saving…':'Save';}
function send(body){$('formErr').textContent='';busy(true);return fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json','X-Wizard-Request':'1'},body:JSON.stringify(body)}).then(function(r){return r.json().catch(function(){return {};}).then(function(j){if(!r.ok||!j.saved)throw new Error(j.error||'Settings were not saved. Try again.');});}).then(function(){dirty=false;}).catch(function(e){$('formErr').textContent=e.message||'Settings were not saved. Try again.';}).then(function(){busy(false);});}
form.addEventListener('input',function(e){if(saving)return;dirty=true;if(e.target===url)$('urlErr').textContent='';});
form.addEventListener('change',function(){if(saving)return;dirty=true;toggleUrl();});
form.addEventListener('submit',function(e){e.preventDefault();if(saving)return;var m=mode(),u=url.value.trim();url.removeAttribute('aria-invalid');
if(m==='another-machine'&&!/^https?:\/\/[^\s\/]+/i.test(u)){$('urlErr').textContent='Enter the machine address, starting with http:// or https://';url.setAttribute('aria-invalid','true');url.focus();return;}
if(!sel.value){$('formErr').textContent='Choose a model.';return;}
send({mode:m,model:sel.value,base_url:m==='another-machine'?u:''});});
$('retry').addEventListener('click',function(){if(saving)return;send({mode:'on-box',model:sel.value||'qwen2.5-1.5b',base_url:''});});
var hosted=false;try{hosted=window.self!==window.top;}catch(e){hosted=true;}
if(!hosted&&window.history&&history.pushState){var note=$('backNote'),last=0,nt=0;
history.pushState({wzGuard:1},'');
window.addEventListener('popstate',function(){var now=Date.now();
if(last&&now-last<2000){note.textContent='';history.back();return;}
last=now;history.pushState({wzGuard:1},'');note.textContent='Press back again to exit';clearTimeout(nt);nt=setTimeout(function(){note.textContent='';last=0;},2000);});}
poll();
})();
