// Narrow hosted-proxy QA: real app assets + explicit status fixture, NOT an installed shell.
// Run on external-volume Thales directly; no heavy-worker lock needed.
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium, devices} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const evidence = path.join(root,'evidence');
await fs.mkdir(evidence,{recursive:true});
// Chromium temporary profiles must never land on the host's internal disk.
process.env.TMPDIR=path.join(evidence,'browser-tmp');
await fs.mkdir(process.env.TMPDIR,{recursive:true});
const catalog=[{id:'qwen2.5-1.5b',label:'Qwen2.5 1.5B Instruct (recommended)',size:1117320736},{id:'qwen2.5-0.5b',label:'Qwen2.5 0.5B Instruct (small test)',size:491400032}];
let state={mode:'on-box',model:'qwen2.5-1.5b',base_url:'',download:{state:'ready',received:1117320736,total:1117320736},models:[{id:'qwen2.5-1.5b',label:'Qwen2.5 1.5B'}],status:'connected',catalog};
const common={canvas:'transparent',base:'#05030c',chrome:'rgba(12,8,26,.82)',overlay:'rgba(28,19,58,.72)',surface:'rgba(243,239,255,.06)','surface-raised':'rgba(243,239,255,.10)',text:'#f3efff','text-secondary':'#b9b0d8','text-muted':'#9e92be',border:'rgba(205,190,255,.24)',accent:'#b99bff','accent-soft':'rgba(185,155,255,.16)','on-accent':'#05030c','reader-surface':'transparent'};
const skins={nebula:common,signal:{...common,base:'#f4f5ef',chrome:'#f4f5ef',overlay:'#f4f5ef',surface:'rgba(12,32,14,.05)','surface-raised':'rgba(12,32,14,.10)',text:'#102614','text-secondary':'#344b37','text-muted':'#4c6150',border:'#839486',accent:'#175829','accent-soft':'rgba(23,88,41,.10)','on-accent':'#ffffff'}};
const hostScript=`const frame=document.querySelector('iframe');let skin='nebula',revision=0;const skins=${JSON.stringify(skins)};function apply(){document.body.style.background=skins[skin].base;document.documentElement.style.colorScheme=skin==='nebula'?'dark':'light';frame.style.colorScheme='inherit';frame.contentWindow.postMessage({type:'wizard:appearance',appearance:{version:1,revision:++revision,skin,colorScheme:skin==='nebula'?'dark':'light',presentation:'window',tokens:skins[skin]}},location.origin);}addEventListener('message',e=>{if(e.origin===location.origin&&e.source===frame.contentWindow&&e.data?.type==='wizard:appearance:ready')apply();});document.querySelectorAll('button').forEach(b=>b.onclick=()=>{skin=b.dataset.skin;apply();});`;
const csp="default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'";
const server=http.createServer(async(req,res)=>{
 try {
  res.setHeader('Content-Security-Policy',csp);res.setHeader('Cache-Control','no-store');
  if(req.url==='/host'){res.setHeader('Content-Type','text/html');return res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/host.css"><script src="/host.js" defer></script></head><body><nav><button data-skin="nebula">Nebula</button><button data-skin="signal">Signal</button></nav><iframe title="Local model" src="/"></iframe></body></html>');}
  if(req.url==='/host.js'){res.setHeader('Content-Type','text/javascript');return res.end(hostScript);}
  if(req.url==='/host.css'){res.setHeader('Content-Type','text/css');return res.end('html,body{margin:0;height:100%;}nav{height:48px;display:flex;gap:12px;padding:4px;}button{min-height:40px;}iframe{border:0;width:100%;height:calc(100vh - 48px);display:block;}');}
  if(req.url==='/sentinel'){res.setHeader('Content-Type','text/html');return res.end('<h1>Prior document</h1>');}
  if(req.url==='/api/status'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(state));}
  if(req.url==='/api/settings' && req.method==='POST'){
   let body='';for await(const c of req)body+=c;
   assert.equal(req.headers['x-wizard-request'],'1');const saved=JSON.parse(body);
   assert.deepEqual(Object.keys(saved).sort(),['base_url','mode','model']);
   state={...state,...saved};res.setHeader('Content-Type','application/json');return res.end('{"saved":true}');
  }
  const assets={'/':'index.html','/app.js':'app.js','/appearance.js':'appearance.js','/styles.css':'styles.css'};
  if(!assets[req.url]){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',req.url.endsWith('.js')?'text/javascript':req.url.endsWith('.css')?'text/css':'text/html');
  return res.end(await fs.readFile(path.join(root,'web',assets[req.url])));
 }catch(e){res.statusCode=500;res.end('QA fixture error');}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const origin='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
const receipt={coverage:'same-origin hosted proxy with status fixture; NOT installed-shell or physical-device proof',checks:[],screenshots:[]};
try{
 for(const [name,profile] of [['desktop',{viewport:{width:1100,height:850}}],['mobile',{...devices['iPhone 13']}]]){
  state={...state,mode:'on-box',base_url:'',status:'connected'};
  const ctx=await browser.newContext(profile);const page=await ctx.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(origin+'/host');const frame=page.frames().find(f=>f.url()===origin+'/');
  assert(frame);await frame.locator('#status').filter({hasText:'Model ready'}).waitFor();
  await frame.locator('input[value="another-machine"]').check();await frame.locator('#url').fill('http://unsaved-machine:11434/v1');
  await frame.evaluate(()=>window.__qaDocument='preserved');
  for(const skin of ['nebula','signal']){
   await page.getByRole('button',{name:skin,exact:false}).click();
   await frame.waitForFunction(s=>document.documentElement.dataset.skin===s,skin);
   assert.equal(await frame.locator('#url').inputValue(),'http://unsaved-machine:11434/v1');
   const computed=await frame.evaluate(()=>({marker:window.__qaDocument,canvas:getComputedStyle(document.body).backgroundColor,overflow:document.documentElement.scrollWidth>innerWidth,width:innerWidth,radius:getComputedStyle(document.querySelector('.card')).borderRadius,scheme:document.documentElement.dataset.colorScheme}));
   assert.equal(computed.marker,'preserved');assert.equal(computed.canvas,'rgba(0, 0, 0, 0)');assert.equal(computed.overflow,false);assert.equal(computed.width,profile.viewport.width);
   assert.equal(computed.scheme,skin==='nebula'?'dark':'light');if(skin==='signal')assert.equal(computed.radius,'2px');
   await frame.locator('#save').scrollIntoViewIfNeeded();
   const shot=path.join(evidence,`${name}-${skin}.png`);await page.screenshot({path:shot,fullPage:true});receipt.screenshots.push(path.basename(shot));
   receipt.checks.push({profile:name,skin,...computed});
  }
  // An untrusted source window cannot change appearance.
  await frame.evaluate(()=>window.postMessage({type:'wizard:appearance',appearance:{skin:'evil'}},location.origin));
  assert.equal(await frame.evaluate(()=>document.documentElement.dataset.skin),'signal');
  await frame.locator('#save').click();await frame.waitForFunction(()=>!document.querySelector('#save').disabled);
  assert.equal(state.mode,'another-machine');assert.equal(state.base_url,'http://unsaved-machine:11434/v1');
  assert.deepEqual(errors,[]);receipt.checks.push({profile:name,save:true,no_page_errors:true});
  await ctx.close();
 }
 const ctx=await browser.newContext({viewport:{width:390,height:844}});const page=await ctx.newPage();
 await page.goto(origin+'/sentinel');await page.goto(origin+'/');
 await page.locator('#status').filter({hasText:'Model ready'}).waitFor();
 await page.evaluate(()=>history.back());
 await page.locator('#backNote').filter({hasText:'Press back again to exit'}).waitFor();
 assert.equal(new URL(page.url()).pathname,'/');
 await page.screenshot({path:path.join(evidence,'standalone-back.png')});
 receipt.checks.push({standalone_first_back_stays:true,standalone_dark:true});
 await page.evaluate(()=>history.back());await page.waitForURL(origin+'/sentinel');
 receipt.checks.push({standalone_second_back_can_exit:true});await ctx.close();
 receipt.passed=true;
}finally{
 await browser.close();server.close();
 await fs.writeFile(path.join(evidence,'appearance-receipt.json'),JSON.stringify(receipt,null,2)+'\n');
 console.log(JSON.stringify(receipt,null,2));
}
