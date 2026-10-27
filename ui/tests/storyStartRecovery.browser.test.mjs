import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

// 真掛載宿主與工作台；僅 transport 為合成 Response，沒有產品 HTTP／PG／模型。
// 所有競態由命名 gate 推進，不以 sleep 或重複輪跑決定時序。
const fixture = String.raw`
import React, {StrictMode, useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {StoryWorld} from './src/StoryWorld.jsx';
import {rememberStart} from './src/startModel.js';
import {i18n} from './src/i18n/index.js';
await i18n.changeLanguage('en');
window.control = {}; window.calls = []; window.events = []; window.unexpected = [];
window.identityLost = 0; window.replay = [];
const actor = {actor_id:'r16-actor', role:'admin'};
const query = new URLSearchParams(location.search);
const scenario = query.get('scenario') || 'lost';
const config = JSON.parse(sessionStorage.getItem('r16-config') || '{}');
window.configure = values => {Object.assign(config,values);sessionStorage.setItem('r16-config',JSON.stringify(config));};
window.gates = {};
window.release = name => gates[name].resolve();
const gate = async name => {
  let resolve;
  const wait = new Promise(done => resolve = done);
  gates[name] = {resolve}; events.push('gate:'+name);
  await wait; events.push('released:'+name);
};
const originalSet = Storage.prototype.setItem;
Storage.prototype.setItem = function(key, value) {
  originalSet.call(this,key,value);
  if (key === 'zf.start:r16') events.push('checkpoint:'+JSON.parse(value).handoff?.stage);
};
if (scenario === 'no-idb') Object.defineProperty(window, 'indexedDB', {value:undefined});
const node = text => ({type:'paragraph', attrs:{bid:'b_original', owner:null, created:null}, content:[{type:'text',text}]});
window.state = JSON.parse(sessionStorage.getItem('r16-server') || 'null') || {source:null, receipt:null, writes:0};
const persist = () => sessionStorage.setItem('r16-server',JSON.stringify(state));
const workspace = epId => ({doc:{type:'doc',content:[node('Working '+epId)]},docHash:'working-'+epId,revision:1,
  structure:{initialized:true,version:1,docHash:'working-'+epId,structureHash:'structure-'+epId,lanes:[],scenes:[]},
  baseline:{},versions:{items:[]},sources:{items:[]},branches:{items:[]},capabilities:{writable:true}});
const response = (value,status=200) => new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
window.fetch = async (url, options={}) => {
  const path = new URL(String(url),location.href).pathname, method=options.method || 'GET';
  const headers = new Headers(options.headers), body=options.body?JSON.parse(options.body):undefined;
  const call = {path,method,body,actor:headers.get('X-Writing-Expected-Actor'),key:headers.get('Idempotency-Key'),signal:options.signal};
  calls.push(call);
  if(path === '/projects/api/r16' || path === '/projects/api/other') return response({me:actor});
  // The episode's crew jobs (SPEC_20 R23) are a plain read outside the writing session.
  if(path === '/aivideo/open/v1/catalog/styles' || /\/episodes\/(ep_r16_01|ep_other_01)\/(assets|crew-jobs)$/.test(path)) return response({code:0,data:{items:[],nextCursor:null}});
  // So is its pre-production flow (SPEC_20 R24, the script view's crew panel): none yet.
  if(/\/episodes\/(ep_r16_01|ep_other_01)\/preproduction$/.test(path) && method === 'GET') return response({code:0,data:{flow:null,next:null,canStart:true,canLock:true}});
  const match = /\/episodes\/(ep_r16_01|ep_other_01)\/writing\/(.+)$/.exec(path);
  if(match) {
    const [,epId,tail] = match;
    if(call.actor !== actor.actor_id) throw new Error('缺少 actor binding');
    if(method !== 'GET' && headers.get('X-Requested-With') !== 'projects') throw new Error('缺少 CSRF 標頭');
    if(tail === 'workspace' && method === 'GET') {
      if(config.holdWorkspace && epId === 'ep_r16_01' && calls.filter(c=>c.path===path).length<=3) await gate('workspace-'+calls.filter(c=>c.path===path).length);
      if(options.signal?.aborted) {events.push('workspace-aborted');throw new DOMException('Aborted','AbortError');}
      return response({code:0,data:workspace(epId)});
    }
    if(tail === 'bible' && method === 'GET') return response({code:0,data:{items:[],nextCursor:null}});
    if(tail === 'sources/novel' && epId === 'ep_r16_01') {
      if(method === 'GET') {
        if(state.source && config.failResource) {events.push('resource-503');return response({message:'定向資源載入失敗'},503);}
        if(state.source && config.holdResource) await gate('resource');
        return response({code:0,data:state.source});
      }
      if(method === 'PUT') {
        if(config.failReplay) {events.push('replay-503');return response({message:'定向 replay 失敗'},503);}
        if(state.receipt) {
          if(JSON.stringify(state.receipt.body)!==JSON.stringify(body) || state.receipt.key!==call.key) throw new Error('重播 body/key 改變');
          events.push('receipt-replay');
        } else {
          if(body.baseVersion!==0) throw new Error('錯誤 CAS');
          state.source={...body,version:1,docHash:'novel-hash-1'};
          if(JSON.parse(sessionStorage.getItem('zf.start:r16')).handoff.stage!=='source-save') throw new Error('mutation 前缺少 durable checkpoint');
          state.receipt={body,key:call.key};state.writes++;persist();events.push('committed');
        }
        if(scenario === 'late' && !config.resume) {
          // 故意忽略 abort 的 transport：必須由產品 actor-bound session 擋下晚到 ACK。
          await gate('ack');events.push('late-ack');
        }
        if(scenario === 'lost' && !config.resume) {events.push('lost-ack');throw new TypeError('定向 ACK 遺失');}
        return response({code:0,data:state.source});
      }
    }
  }
  unexpected.push({path,method});throw new Error('未知合成路由 '+method+' '+path);
};
if(!sessionStorage.getItem('r16-started')) {
  rememberStart('r16',{mode:'novel',text:'Original pending prose. Never lose this.',ratio:'16:9',style:'88123',handoffId:'r16-directed-start'});
  sessionStorage.setItem('r16-started','yes');
}
function ReplayProbe() {useEffect(()=>{replay.push('setup');return()=>replay.push('cleanup');},[]);return null;}
const root=createRoot(document.getElementById('root'));
window.mountEpisode = epId => root.render(<StrictMode><ReplayProbe/><StoryWorld key={epId}
  slug={epId==='ep_r16_01'?'r16':'other'} epId={epId} me={actor} ep={{episodeId:epId,settings:{},scenes:[],scriptContent:'Working '+epId}}
  writable controlRef={control} onIdentityLost={identityLost}/></StrictMode>);
function identityLost() {window.identityLost++;}
mountEpisode('ep_r16_01');
`;

const python = String.raw`
import json
from playwright.sync_api import sync_playwright, expect
BASE = '__BASE__'
TEXT = 'Original pending prose. Never lose this.'
with sync_playwright() as p:
 browser = p.chromium.launch(headless=True)
 def pending(page):
  return page.evaluate("JSON.parse(sessionStorage.getItem('zf.start:r16'))")
 def config(page, **values):
  page.evaluate('(v)=>sessionStorage.setItem("r16-config",JSON.stringify(v))',values)
 def ready(page, episode, kind='working'):
  page.wait_for_function('([ep,kind])=>control.current?.consoleContext().episodeId===ep && control.current.consoleContext().sourceRef.kind===kind && !!control.current.consoleContext().docHash',arg=[episode,kind])
  assert page.evaluate('control.current.consoleContext().docHash') == ('novel-hash-1' if kind=='source' else 'working-'+episode)
 def opened(page):
  ready(page,'ep_r16_01','source')
  expect(page.get_by_role('combobox',name='Manuscript',exact=True)).to_have_value('source:novel')
  expect(page.get_by_role('textbox',name='Manuscript editor',exact=True)).to_contain_text(TEXT)
  expect(page.locator('.writing-start-recovery')).to_have_count(0)
  assert pending(page) is None
 def failed(page):
  expect(page.locator('.writing-start-recovery [role=alert]')).to_be_visible()
  expect(page.locator('.writing-start-recovery button').first).to_be_enabled()
  ready(page,'ep_r16_01')
  assert pending(page)['text']==TEXT
 def clean(page, errors):
  assert page.evaluate('unexpected')==[],page.evaluate('unexpected')
  assert page.evaluate('window.identityLost')==0
  assert page.evaluate("calls.filter(c=>c.path.includes('/writing/')).every(c=>c.actor==='r16-actor')")
  assert errors==[],errors
  assert page.evaluate('replay')==['setup','cleanup','setup']
 results=[]
 def trace(page, phase):
  return {'phase':phase,'events':page.evaluate('events'),'checkpoint':(pending(page) or {}).get('handoff',{}).get('stage'),
   'calls':page.evaluate('calls.map(({signal,...call})=>({...call,aborted:signal?.aborted}))')}
 for scenario in ['lost','resource-failure','replay-failure','late','no-idb']:
  context=browser.new_context()
  page=context.new_page(); errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  phases=[]
  if scenario=='resource-failure':
   page.add_init_script("if(!sessionStorage.getItem('r16-config'))sessionStorage.setItem('r16-config',JSON.stringify({failResource:true}))")
  try:
   page.goto(BASE+'/?scenario='+('lost' if scenario=='replay-failure' else scenario))
   if scenario in ['lost','replay-failure']:
    failed(page)
    before=pending(page)['handoff']['request']
    assert pending(page)['handoff']['stage']=='source-save'
    assert page.evaluate('state.writes')==1
    phases.append(trace(page,'ACK 遺失後'))
    # reload 的 workspace／source GET 分別阻擋；檢查 ACK 前後 checkpoint。
    config(page,resume=True,holdWorkspace=scenario=='lost',holdResource=scenario=='lost',failReplay=scenario=='replay-failure')
    page.reload()
    if scenario=='lost':
     page.wait_for_function("gates['workspace-1'] && gates['workspace-2']")
     assert pending(page)['handoff']['request']==before
     assert page.evaluate("calls.filter(c=>c.method==='PUT').length")==0
     page.evaluate("release('workspace-2')")
     page.wait_for_function("gates['workspace-3']")
     assert pending(page)['handoff']['stage']=='done'
     page.evaluate("release('workspace-3')")
     page.wait_for_function('gates.resource')
     assert pending(page)['handoff']['stage']=='done'
     ready(page,'ep_r16_01')
     assert page.evaluate('state.writes')==1
     assert page.evaluate("calls.filter(c=>c.method==='PUT').map(c=>c.body)")==[before['body']]
     page.evaluate("release('resource')")
     opened(page)
     # StrictMode 舊 initial load 最後才回；loadSequence 必須忽略，不能覆蓋小說。
     page.evaluate("release('workspace-1')")
     page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    else:
     failed(page)
     assert pending(page)['handoff']['stage']=='source-save'
     phases.append(trace(page,'replay 503，尚未明確重試'))
     count=page.evaluate("calls.filter(c=>c.method==='PUT').length")
     page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
     assert page.evaluate("calls.filter(c=>c.method==='PUT').length")==count
     page.evaluate('configure({failReplay:false})')
     page.locator('.writing-start-recovery button').first.click()
    opened(page)
    assert page.evaluate('state.receipt.body')==before['body']
    assert page.evaluate('state.writes')==1
   elif scenario=='resource-failure':
    failed(page)
    assert pending(page)['handoff']['stage']=='done'
    assert page.evaluate('state.writes')==1
    phases.append(trace(page,'已 ACK 但資源 GET 503'))
    # 保留 done checkpoint reload 再失敗，不能重送 PUT；明確 Retry 才重載。
    page.reload();failed(page)
    assert pending(page)['handoff']['stage']=='done'
    assert page.evaluate("calls.filter(c=>c.method==='PUT').length")==0
    page.evaluate('configure({failResource:false})')
    page.locator('.writing-start-recovery button').first.click();opened(page)
    assert page.evaluate("calls.filter(c=>c.method==='PUT').length")==0
   elif scenario=='late':
    page.wait_for_function('gates.ack')
    before=pending(page)['handoff']['request']
    ready(page,'ep_r16_01')
    assert page.evaluate('state.writes')==1
    page.evaluate("mountEpisode('ep_other_01')")
    ready(page,'ep_other_01')
    page.wait_for_function("calls.find(c=>c.method==='PUT').signal.aborted")
    assert pending(page)['handoff']['stage']=='source-save'
    page.evaluate("release('ack')")
    page.wait_for_function("events.includes('late-ack')")
    # 等候晚到 Response 的 promise 鏈完全清空（事件迴圈 barrier，不是 sleep）。
    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    ready(page,'ep_other_01')
    assert pending(page)['handoff']['request']==before
    assert pending(page)['handoff']['stage']=='source-save'
    phases.append(trace(page,'換集 abort 後收到晚到 ACK'))
    config(page,resume=True);page.reload();opened(page)
    assert page.evaluate('state.writes')==1
   else:
    opened(page)
    assert page.evaluate('typeof indexedDB')=='undefined'
    assert page.evaluate('state.writes')==1
   assert page.evaluate('state.source.version')==1
   clean(page,errors)
   phases.append(trace(page,'小說已載入且 pending 已刪除'))
   results.append({'scenario':scenario,'writes':page.evaluate('state.writes'),'phases':phases})
  except Exception:
   print(json.dumps({"案例":scenario,"診斷":trace(page,"失敗"),"畫面":page.locator(".authoring-workspace").inner_text()},ensure_ascii=False),flush=True)
   raise
  context.close()
 print(json.dumps({'結果':'通過','邊界':'真 Chromium／development StrictMode；合成 fetch Response，非 HTTP／PG','案例':results},ensure_ascii=False))
 browser.close()
`;

test('R16 定向 ACK／reload／abort／資源載入與 StrictMode 邊界（合成 transport）', {timeout:90000}, async () => {
  const bundle = await build({stdin:{contents:fixture,resolveDir:fileURLToPath(new URL('..',import.meta.url)),loader:'jsx'},
    bundle:true,write:false,format:'esm',jsx:'automatic',loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"development"'}});
  const server=createServer((req,res)=>{
    if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');res.end(bundle.outputFiles[0].text);}
    else {res.setHeader('Content-Type','text/html');res.end('<!doctype html><div id="root"></div><script type="module" src="/app.js"></script>');}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {
    const output=await new Promise((resolve,reject)=>{
      const child=spawn('python',['-X','utf8','-c',python.replace('__BASE__',`http://127.0.0.1:${server.address().port}`)],{timeout:80000});
      let stdout='',stderr='';
      child.stdout.on('data',chunk=>stdout+=chunk);child.stderr.on('data',chunk=>stderr+=chunk);
      child.on('error',reject);child.on('close',code=>resolve({code,stdout,stderr}));
    });
    assert.equal(output.code,0,output.stdout+'\n'+output.stderr);
    console.log(output.stdout.trim());
  } finally {await new Promise(resolve=>server.close(resolve));}
});
