import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const uiRoot = fileURLToPath(new URL('..', import.meta.url));
// Real development React and Chromium; only fetch responses are synthetic. This is
// NOT product HTTP/auth/database evidence, and must never call a provider or GPU.
const fixture = String.raw`
import React, {StrictMode, useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {StoryWorld} from './src/StoryWorld.jsx';
import {i18n} from './src/i18n/index.js';
await i18n.changeLanguage('en');
window.control = {};
window.calls = [];
window.unexpected = [];
window.replay = [];
window.identityLost = 0;
window.failMetadata = false;
const actor = {actor_id:'strict-actor', role:'admin'};
const epId = 'ep_strict_01';
const node = (bid, text, type = 'paragraph') => ({type, attrs:{bid, owner:null, created:null,
  ...(type === 'heading' ? {level:2} : {})}, content:[{type:'text', text}]});
window.state = JSON.parse(sessionStorage.getItem('strict-server') || 'null') || {
  revision:1, summary:'', doc:{type:'doc', content:[
    node('heading', 'Scene 01: The signal', 'heading'), node('body', 'Original action.')
  ]}
};
const persist = () => sessionStorage.setItem('strict-server', JSON.stringify(window.state));
const structure = () => ({initialized:true, version:state.revision, docHash:'hash'+state.revision,
  structureHash:'structure'+state.revision, lanes:[], scenes:[{sceneKey:'scene1',
    headingBid:'heading', title:'Scene 01: The signal', order:1, mapping:'exact',
    blockBids:['body'], beats:[{beatKey:'beat1', blockBids:['body']}], summary:state.summary}]});
const workspace = () => ({doc:state.doc, docHash:'hash'+state.revision, revision:state.revision,
  structure:structure(), versions:{items:[]}, sources:{items:[]}, branches:{items:[]},
  baseline:{}, capabilities:{writable:true}});
window.fetch = async (url, options = {}) => {
  const path = new URL(String(url), location.href).pathname;
  const method = options.method || 'GET';
  const headers = new Headers(options.headers);
  const body = options.body ? JSON.parse(options.body) : undefined;
  const call = {path, method, body, actor:headers.get('X-Writing-Expected-Actor'),
    csrf:headers.get('X-Requested-With'), signal:options.signal};
  window.calls.push(call);
  // Leave requests asynchronous so the StrictMode cleanup/setup runs before ACKs.
  await new Promise(resolve => setTimeout(resolve, 10));
  if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const response = (value, status = 200) => new Response(JSON.stringify(value),
    {status, headers:{'Content-Type':'application/json'}});
  if (path === '/projects/api/strict') return response({me:actor});
  const base = '/aivideo/open/v1';
  if (path === base+'/catalog/styles' || path === base+'/episodes/'+epId+'/assets')
    return response({code:0, data:{items:[], nextCursor:null}});
  const tail = path.split('/episodes/'+epId+'/writing/')[1];
  if (tail) {
    if (call.actor !== actor.actor_id) throw new Error('Missing actor binding: '+path);
    if (method !== 'GET' && call.csrf !== 'projects') throw new Error('Missing write header');
    if (tail === 'workspace' && method === 'GET') return response({code:0, data:workspace()});
    if (tail === 'bible' && method === 'GET')
      return response({code:0, data:{items:[], nextCursor:null}});
    if (tail === 'script/ops' && method === 'POST') {
      for (const op of body.ops) {
        const at = state.doc.content.findIndex(node => node.attrs.bid === op.bid);
        if (op.op === 'put') {
          if (at < 0) throw new Error('Fixture expects an existing paragraph');
          state.doc.content[at] = op.node;
        } else throw new Error('Unexpected script operation: '+op.op);
      }
      state.revision++; persist();
      return response({code:0, data:{...workspace(), version:state.revision,
        clientMutationId:body.clientMutationId, conflicts:[], savedAt:new Date().toISOString()}});
    }
    if (tail === 'structure/metadata' && method === 'PATCH') {
      if (window.failMetadata) return response({message:'Synthetic outline offline'}, 500);
      if (body.baseVersion !== state.revision) return response({message:'Structure changed'}, 409);
      if (body.scenePatches.length !== 1 || body.scenePatches[0].sceneKey !== 'scene1')
        throw new Error('Unexpected outline patch');
      state.summary = body.scenePatches[0].summary; state.revision++; persist();
      return response({code:0, data:{...structure(), clientMutationId:body.clientMutationId}});
    }
  }
  window.unexpected.push({path, method});
  throw new Error('Unexpected synthetic fetch: '+method+' '+path);
};
function ReplayProbe() {
  useEffect(() => {window.replay.push('setup'); return () => window.replay.push('cleanup');}, []);
  return null;
}
const ep = {episodeId:epId, settings:{}, scenes:[], assets:[], scriptContent:'Original action.'};
createRoot(document.getElementById('root')).render(<StrictMode>
  <ReplayProbe/>
  <StoryWorld slug="strict" epId={epId} me={actor} ep={ep} writable controlRef={window.control}
    onIdentityLost={() => window.identityLost++}/>
</StrictMode>);
`;

test('StoryWorld development StrictMode replays effects, keeps actor-bound saves and restores outline drafts (synthetic transport)', {timeout:90000}, async () => {
  const bundle = await build({stdin:{contents:fixture, resolveDir:uiRoot, loader:'jsx'},
    bundle:true, write:false, format:'esm', jsx:'automatic', loader:{'.css':'empty'},
    define:{'process.env.NODE_ENV':'"development"'}});
  const server = createServer((req, res) => {
    if (req.url === '/app.js') {
      res.setHeader('Content-Type', 'text/javascript'); res.end(bundle.outputFiles[0].text);
    } else if (req.url === '/') {
      res.setHeader('Content-Type', 'text/html');
      res.end('<!doctype html><div id="root"></div><script type="module" src="/app.js"></script>');
    } else {res.statusCode = 404; res.end();}
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const python = String.raw`
import json
from playwright.sync_api import sync_playwright, expect
with sync_playwright() as p:
 browser = p.chromium.launch(headless=True)
 context = browser.new_context(viewport={'width':1280,'height':720})
 page = context.new_page()
 errors = []
 page.on('pageerror', lambda error: errors.append(str(error)))
 page.goto('http://127.0.0.1:${server.address().port}/')
 editor = page.get_by_role('textbox', name='Manuscript editor', exact=True)
 expect(editor).to_contain_text('Original action.')
 expect(editor).to_be_editable()
 # A production React bundle or a mere double render cannot satisfy this sequence.
 assert page.evaluate('window.replay') == ['setup','cleanup','setup']
 page.wait_for_function("control.current?.recoveryState().tools?.some(t => t.key === 'outline:metadata' && t.state === 'saved')")
 assert page.evaluate('control.current.consoleContext().episodeId') == 'ep_strict_01'
 editor.locator('p').first.click()
 page.keyboard.press('End')
 page.keyboard.type(' Saved after real replay.')
 page.keyboard.press('Control+s')
 page.wait_for_function("state.doc.content.some(n => JSON.stringify(n).includes('Saved after real replay.')) && control.current.isDirty() === false")
 expect(editor).to_contain_text('Saved after real replay.')
 assert page.evaluate("calls.some(c => c.path.endsWith('/script/ops') && c.actor === 'strict-actor')")
 page.get_by_role('button', name='Plot overview', exact=True).click()
 page.evaluate('window.failMetadata = true')
 summary = page.locator('.writing-scene-metadata textarea').first
 summary.fill('Recover this outline after StrictMode replay.')
 assert page.evaluate('control.current.isDirty()') is True
 page.keyboard.press('Control+s')
 page.wait_for_function("control.current.recoveryState().tools.some(t => t.key === 'outline:metadata' && t.state === 'local_only' && t.recoverable)")
 assert page.evaluate('control.current.flush()') is True
 assert page.evaluate('state.summary') == ''
 assert page.evaluate("calls.some(c => c.path.endsWith('/structure/metadata') && c.actor === 'strict-actor')")
 page.reload()
 expect(editor).to_contain_text('Saved after real replay.')
 expect(page.get_by_role('button', name='Restore outline draft for review', exact=True)).to_be_visible()
 assert page.evaluate('window.replay') == ['setup','cleanup','setup']
 # Discovery/restoration is review only: no automatic publication of the private draft.
 assert page.evaluate("calls.filter(c => c.path.endsWith('/structure/metadata')).length") == 0
 page.get_by_role('button', name='Restore outline draft for review', exact=True).click()
 page.get_by_role('button', name='Plot overview', exact=True).click()
 expect(summary).to_have_value('Recover this outline after StrictMode replay.')
 assert page.evaluate("calls.filter(c => c.path.endsWith('/structure/metadata')).length") == 0
 page.keyboard.press('Control+s')
 page.wait_for_function("state.summary === 'Recover this outline after StrictMode replay.' && control.current.isDirty() === false")
 assert page.evaluate("calls.filter(c => c.path.endsWith('/structure/metadata')).map(c => c.body.baseVersion)") == [2]
 page.reload()
 expect(editor).to_contain_text('Saved after real replay.')
 page.get_by_role('button', name='Plot overview', exact=True).click()
 expect(summary).to_have_value('Recover this outline after StrictMode replay.')
 expect(page.get_by_role('button', name='Restore outline draft for review', exact=True)).to_have_count(0)
 assert page.evaluate("calls.filter(c => c.path.includes('/writing/')).every(c => c.actor === 'strict-actor')")
 assert page.evaluate('window.identityLost') == 0
 assert page.evaluate('window.unexpected') == [], page.evaluate('window.unexpected')
 assert errors == [], errors
 print(json.dumps({'result':'PASS','browser':'real Chromium','react':'development',
   'effectReplay':page.evaluate('window.replay'),'transport':'synthetic fetch Response; not product HTTP evidence'}))
 context.close()
 browser.close()
`;
  try {
    const output = await new Promise((resolve, reject) => {
      const child = spawn('python', ['-X', 'utf8', '-c', python], {timeout:80000});
      let stdout = '', stderr = '';
      child.stdout.on('data', chunk => stdout += chunk);
      child.stderr.on('data', chunk => stderr += chunk);
      child.on('error', reject);
      child.on('close', code => resolve({code, stdout, stderr}));
    });
    assert.equal(output.code, 0, output.stdout+'\n'+output.stderr);
    console.log(output.stdout.trim());
  } finally {await new Promise(resolve => server.close(resolve));}
});
