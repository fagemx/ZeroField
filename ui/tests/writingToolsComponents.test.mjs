import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {build} from '../node_modules/esbuild/lib/main.js';

// Real React DOM interactions in Chromium, with only the injected writing transport synthetic.
// No App wiring, provider inference or shared dependency mutation is involved.
const fixture = String.raw`
import React from 'react';
import {createRoot} from 'react-dom/client';
import {WritingToolsPanel} from './src/writing/WritingToolsPanel.jsx';
import {i18n} from './src/i18n/index.js';
import en from './src/writing/locales/tools.en.json';
import zh from './src/writing/locales/tools.zh-TW.json';
i18n.addResourceBundle('en','translation',{writing:{tools:en}},true,true);
i18n.addResourceBundle('zh-TW','translation',{writing:{tools:zh}},true,true);
window.calls=[];window.navigation=[];window.fail={};window.actor='actor-a';window.flushOk=true;window.delayUpload=false;
const expiresAt=Date.now()/1000+1800;
const workspace={doc:{type:'doc',content:[]},docHash:'working-hash',structure:{scenes:[{sceneKey:'wsc_1',title:'Arrival'}]},
  sources:{items:[{mode:'novel',sourceId:'source-1'}]},branches:{items:[{branchId:'branch-1',name:'Alternate'}]},versions:{items:[{versionId:'version-1',name:'Silent ending'}],nextCursor:'next-version-page'}};
let bible={bibleId:'bible-1',entryKind:'asset_extension',assetId:'asset-1',version:1,aliases:['Keeper'],role:'Custodian',background:'Near the sea',constraints:'',relationships:'',rules:'',research:'',notes:'Original note',events:[],asset:{assetId:'asset-1',assetCode:'CAST-01',name:'The Keeper'},continuityWarnings:[]};
let previewCount=0;
const importText='Chapter 1\n😀 Keeper waits.\n';
const upload={previewId:'upload-1',kind:'import',version:1,status:'pending',expiresAt,uploadHash:'upload-hash',purpose:'novel',filename:'chapter.txt',sections:[{sectionId:'sec_1',title:'Chapter 1',start:0,end:Array.from(importText).length}],allowedActions:[{actionId:'import_document'}],proposedChanges:{actions:[{actionId:'import_document'}],text:importText},warnings:['Tables and embedded images are not retained.']};
async function transport(tail,method='GET',body,options={}){
  window.calls.push({tail,method,body:body instanceof Blob?{blob:true,size:body.size}:structuredClone(body),options:{...options,signal:undefined}});
  if(window.fail[tail]){const failure=window.fail[tail];delete window.fail[tail];throw Object.assign(new Error('Synthetic failure'),failure);}
  if(tail.startsWith('bible?'))return {items:[{bibleId:bible.bibleId,assetId:bible.assetId,asset:bible.asset}],nextCursor:null};
  if(tail==='bible/bible-1'&&method==='GET')return structuredClone(bible);
  if(tail==='bible/bible-1'&&method==='PATCH'){Object.assign(bible,body.patch);bible.version++;return {bibleId:bible.bibleId,version:bible.version,savedAt:'now',clientMutationId:body.clientMutationId};}
  if(tail.startsWith('appearances?'))return {rows:[{subjectId:'asset-1',asset:bible.asset,explicitSceneCount:1,mentionCount:3,cells:[{sceneKey:'wsc_1',explicitReference:true,shotCount:1,shotIds:['shot-1'],mentionCount:3}]}]};
  if(tail==='search')return {items:[{matchId:'match-1',resourceRef:{sourceRef:{kind:'working'}},docHash:'working-hash',version:1,blockKey:'block-1',path:[1],start:2,end:8,before:'Keeper',contextBefore:'😀 ',contextAfter:' waits.',sceneKey:'wsc_1',editable:true,protected:false},{matchId:'match-ro',resourceRef:{sourceRef:{kind:'version',id:'version-1'}},docHash:'version-hash',version:1,blockKey:'block-2',start:0,end:6,before:'Keeper',contextAfter:' immutable.',editable:false,protected:false},{matchId:'match-tag',resourceRef:{sourceRef:{kind:'working'}},blockKey:'block-3',start:0,end:8,before:'@CAST-01',editable:true,protected:true}],total:3,nextCursor:null};
  if(tail==='previews'&&body.kind==='replace'){previewCount++;return {previewId:'replace-'+previewCount,kind:'replace',version:1,status:'pending',expiresAt,allowedActions:[{actionId:'match-1'}],proposedChanges:{actions:[{actionId:'match-1',blockKey:'block-1',before:'Keeper',after:body.replacement}]},warnings:[]};}
  if(tail.startsWith('previews/replace-')&&tail.endsWith('/apply'))return {replaced:1,resources:[]};
  if(tail==='imports'){if(window.delayUpload)await new Promise(resolve=>window.releaseUpload=resolve);return structuredClone(upload);}
  if(tail==='previews'&&body.kind==='import')return {...structuredClone(upload),previewId:'revised-1',sections:body.sections,proposedChanges:{text:importText,sections:body.sections,actions:[{actionId:'import_document'}]},warnings:['Excluded ranges are explicit.']};
  if(tail==='previews/revised-1/apply'||tail==='previews/upload-1/apply')return {sourceRef:{kind:'source',mode:'novel'},resourceId:'source-1',docHash:'imported',version:1};
  if(tail==='workspace'){if(window.delayResource)await new Promise(resolve=>window.releaseResource=resolve);return structuredClone(workspace);}
  if(tail.startsWith('versions?'))return {items:[{versionId:'version-2',name:'Another ending'}],nextCursor:null};
  if(tail==='versions/version-1')return {snapshot:{docHash:'version-hash',structure:workspace.structure}};
  if(tail==='sources/novel'||tail==='branches/branch-1')return {docHash:'private-hash',structure:workspace.structure};
  if(tail==='exports')return {exportId:'export-1',format:body.format,filename:body.format==='print'?'story.html':'story.docx',sourceHash:body.expectedHash,expiresAt,contentPath:'exports/export-1/content',delivery:body.format==='print'?'print':'download',warnings:[]};
  if(tail==='exports/export-1/content')return options.responseType==='text'?'<h1>稿件 &lt;script&gt;</h1><p onclick="parent.pwned=true">Keeper</p><script>parent.pwned=true</script><img src="https://invalid.test/tracker"><style>body{display:none}</style>':new Blob(['Synthetic DOCX delivery bytes 稿件'],{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
  throw new Error('Unhandled synthetic endpoint: '+method+' '+tail);
}
const root=createRoot(document.getElementById('root'));
window.renderTools=()=>root.render(React.createElement(React.StrictMode,null,React.createElement(WritingToolsPanel,{slug:'production',epId:'episode-1',me:{actor_id:window.actor},writable:window.viewer!==true,workspace,resourceRef:{kind:'working'},selectedSceneKeys:['wsc_1'],selectedSubjectId:'asset-1',transport,
  flush:async options=>{window.calls.push({flush:options});return window.flushOk;},reload:async()=>window.calls.push({reload:true}),onChanged:result=>window.calls.push({changed:result}),onNavigateSource:ref=>window.navigation.push(ref),onNavigateShots:ref=>window.navigation.push(ref)})));
window.locale=language=>i18n.changeLanguage(language);
window.renderTools();
`;

const driver = String.raw`
import os,json,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 context=browser.new_context(accept_downloads=True,viewport={'width':768,'height':900})
 page=context.new_page()
 errors=[]
 external=[]
 page.on('request',lambda request:external.append(request.url) if request.url.startswith('https://') else None)
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(os.environ['WRITING_TOOLS_TEST_URL'])
 panel=page.get_by_role('complementary',name='Writing tools')
 expect(panel).to_be_visible()
 assert not page.evaluate("calls.some(c=>c.method==='POST'||c.method==='PATCH'||c.tail?.startsWith('sources/'))"), 'Recovery registration must not publish drafts or eagerly read private manuscript sources'
 page.get_by_role('button',name='World & notes',exact=True).click()
 bible=page.get_by_role('region',name='World & notes')
 expect(bible.get_by_role('textbox',name='Notes',exact=True)).to_have_value('Original note')
 bible.get_by_role('textbox',name='Notes',exact=True).fill('New author note <script>not HTML</script>')
 expect(bible.get_by_role('status')).to_contain_text('Private form changes')
 bible.get_by_role('button',name='Add event',exact=True).click()
 bible.get_by_label('Event kind').fill('knowledge')
 bible.get_by_label('Event note').fill('Learns the signal is wrong')
 assert not bible.get_by_label('Explicitly include this visible state').is_checked()
 bible.get_by_label('Explicit state dimension').fill('lamp')
 bible.get_by_label('Explicit state value').fill('broken')
 bible.get_by_role('button',name='Save changes',exact=True).click()
 expect(bible.get_by_role('status').filter(has_text='Saved on the server')).to_be_visible()
 sent=page.evaluate("calls.find(c=>c.method==='PATCH').body")
 assert sent['baseVersion']==1 and sent['clientMutationId']
 assert 'assetId' not in sent['patch'] and 'title' not in sent['patch'] and 'name' not in sent['patch']
 assert sent['patch']['events'][0]['subjectId']=='asset-1' and sent['patch']['events'][0]['sceneKey']=='wsc_1'
 assert sent['patch']['events'][0]['productionRelevant'] is False
 assert sent['patch']['events'][0]['stateValue']=='broken'
 bible.get_by_role('button',name='Refresh',exact=True).last.click()
 expect(bible.get_by_role('button',name='Linked shots: 1')).to_be_visible()
 bible.get_by_role('button',name='Explicit references: 1',exact=True).click()
 bible.get_by_role('button',name='Linked shots: 1').click()
 assert page.evaluate('navigation')==[{'sceneKey':'wsc_1'},{'shotIds':['shot-1']}]
 # Live DOM search, immutable/protected selection, preview and atomic-action-only apply.
 page.keyboard.press('Control+Shift+F')
 search=page.get_by_role('region',name='Search & replace')
 expect(search.get_by_label('Literal search text')).to_be_focused()
 search.get_by_label('Literal search text').fill('Keeper')
 search.get_by_role('button',name='Search selected scope').click()
 expect(search.get_by_text('😀 ',exact=False).first).to_be_visible()
 expect(search.get_by_role('checkbox',name='Select match: Keeper').nth(1)).to_be_disabled()
 expect(search.get_by_role('checkbox',name='Select match: @CAST-01')).to_be_disabled()
 search.get_by_role('checkbox',name='Select match: Keeper').first.check()
 search.get_by_label('Replacement text').fill('Custodian')
 search.get_by_role('button',name='Preview selected replacements').click()
 expect(search.get_by_text('Custodian',exact=True)).to_be_visible()
 sent=page.evaluate("calls.filter(c=>c.tail==='previews'&&c.body.kind==='replace').at(-1).body")
 assert sent['matchIds']==['match-1'] and sent['scope']==[{'sourceRef':{'kind':'working'}}]
 assert page.evaluate("calls.some(c=>c.flush&&c.flush.requireServer===true)")
 search.get_by_role('checkbox',name='Select frozen change: match-1').check()
 page.evaluate("fail['previews/replace-1/apply']={status:409,code:'DRAMA_WRITING_PREVIEW_STALE'}")
 search.get_by_role('button',name='Apply selected changes').click()
 expect(search.get_by_role('alert').first).to_contain_text('stale')
 expect(search.get_by_role('button',name='Apply selected changes')).to_be_disabled()
 page.evaluate("fail['previews']={status:409,code:'DRAMA_WRITING_LOCKED'}")
 search.get_by_role('button',name='Preview selected replacements').click()
 expect(search.get_by_role('alert').first).to_contain_text('locked or read-only')
 expect(search.get_by_role('button',name='Retry the same request')).to_have_count(0)
 search.get_by_role('button',name='Preview selected replacements').click()
 search.get_by_role('checkbox',name='Select frozen change: match-1').check()
 search.get_by_role('button',name='Apply selected changes').click()
 expect(search.get_by_role('status')).to_contain_text('acknowledged by the server')
 sent=page.evaluate("calls.filter(c=>c.tail==='previews/replace-2/apply').at(-1).body")
 assert sent=={'expectedPreviewVersion':1,'selection':{'actions':[{'actionId':'match-1'}]}}
 # A lost ACK retry retains the exact POST identity and body, never force-rebases.
 search.get_by_role('button',name='Search selected scope').click()
 search.get_by_role('checkbox',name='Select match: Keeper').first.check()
 page.evaluate("fail['previews']={status:503}")
 search.get_by_role('button',name='Preview selected replacements').click()
 search.get_by_role('button',name='Retry the same request').click()
 expect(search.get_by_role('checkbox',name='Select frozen change: match-1')).to_be_visible()
 retries=page.evaluate("calls.filter(c=>c.tail==='previews'&&c.body.kind==='replace').slice(-2)")
 assert retries[0]['body']==retries[1]['body'] and retries[0]['options']['idempotencyKey']==retries[1]['options']['idempotencyKey']
 # Server-only checkpoint failure cannot produce another preview.
 page.evaluate('flushOk=false')
 search.get_by_role('button',name='Preview selected replacements').click()
 expect(search.get_by_role('alert')).to_contain_text('device-only checkpoint')
 page.evaluate('flushOk=true')
 # Esc returns focus to the tool trigger; switching tools does not recreate editor/tool drafts.
 search.get_by_label('Replacement text').focus()
 page.keyboard.press('Escape')
 expect(page.get_by_role('button',name='Search & replace',exact=True)).to_be_focused()
 page.get_by_role('button',name='Import & export',exact=True).click()
 files=page.get_by_role('region',name='Import & export')
 files.get_by_label('Manuscript file').set_input_files({'name':'章節.txt','mimeType':'text/plain','buffer':'Chapter 1\n😀 Keeper waits.\n'.encode()})
 files.get_by_role('button',name='Upload for private preview').click()
 expect(files.get_by_text('Private preview only',exact=False)).to_be_visible()
 sent=page.evaluate("calls.find(c=>c.tail==='imports')")
 assert sent['options']['raw'] is True and sent['options']['headers']['X-Writing-Purpose']=='novel'
 assert sent['options']['headers']['X-Filename']=='%E7%AB%A0%E7%AF%80.txt'
 files.get_by_label('Section title').fill('Arrival revised')
 expect(files.get_by_role('button',name='Confirm private import')).to_have_count(0)
 files.get_by_role('button',name='Preview corrected boundaries').click()
 expect(files.get_by_role('button',name='Confirm private import')).to_be_enabled()
 sent=page.evaluate("calls.filter(c=>c.tail==='previews'&&c.body.kind==='import').at(-1).body")
 assert sent['uploadPreviewId']=='upload-1' and sent['uploadHash']=='upload-hash'
 assert sent['sections'][0]['title']=='Arrival revised' and isinstance(sent['sections'][0]['start'],int)
 files.get_by_role('button',name='Cancel',exact=True).click()
 expect(files.get_by_role('status').last).to_contain_text('cancelled locally')
 assert not page.evaluate("calls.some(c=>c.tail==='previews/revised-1/apply')")
 # Cancel while upload is in flight: late private preview never reappears or changes manuscript.
 page.evaluate('delayUpload=true')
 files.get_by_label('Manuscript file').set_input_files({'name':'late.txt','mimeType':'text/plain','buffer':b'late'})
 files.get_by_role('button',name='Upload for private preview').click()
 files.get_by_role('button',name='Cancel',exact=True).click()
 page.evaluate('releaseUpload();delayUpload=false')
 expect(files.get_by_role('status').last).to_contain_text('cancelled locally')
 expect(files.get_by_role('button',name='Confirm private import')).to_have_count(0)
 # Confirming an import submits only the frozen import_document action; not a mainline overwrite.
 files.get_by_label('Manuscript file').set_input_files({'name':'chapter.txt','mimeType':'text/plain','buffer':b'Chapter 1'})
 files.get_by_role('button',name='Upload for private preview').click()
 files.get_by_role('button',name='Confirm private import').click()
 expect(files.get_by_role('status')).to_contain_text('Private import acknowledged')
 sent=page.evaluate("calls.filter(c=>c.tail==='previews/upload-1/apply').at(-1).body")
 assert sent['selection']=={'actions':[{'actionId':'import_document'}]}
 # Version catalog pagination loads summaries, not private/full documents.
 files.get_by_role('button',name='Load more shared versions').click()
 expect(files.get_by_label('Manuscript / version').locator('option',has_text='Another ending')).to_have_count(1)
 assert not page.evaluate("calls.some(c=>c.tail==='versions/version-2')")
 # Version/range export reads selected snapshot hash; private bytes use injected authenticated transport.
 files.get_by_label('Manuscript / version').select_option(label='Shared version: Silent ending')
 files.get_by_label('Scene range').select_option('selected')
 files.get_by_role('button',name='Prepare fixed export',exact=True).click()
 expect(files.get_by_role('status').last).to_contain_text('No file has been saved')
 sent=page.evaluate("calls.filter(c=>c.tail==='exports').at(-1).body")
 assert sent=={'sourceRef':{'kind':'version','id':'version-1'},'expectedHash':'version-hash','sceneKeys':['wsc_1'],'format':'docx','include':{'summaries':False,'bibleIds':[]}}
 with page.expect_download() as info: files.get_by_role('button',name='Download file').click()
 download=info.value
 assert download.suggested_filename=='story.docx'
 assert '稿件' in Path(download.path()).read_bytes().decode()
 expect(files.get_by_role('status').last).to_contain_text('save completion is not observable')
 page.evaluate("fail['exports/export-1/content']={status:403}")
 files.get_by_role('button',name='Download file').click()
 expect(files.get_by_role('alert')).to_contain_text('No automatic upload or retry')
 expect(files.get_by_role('button',name='Download file')).to_have_count(0)
 # Browser PDF flow is an inert sanitized print view, not a fabricated server PDF.
 files.get_by_label('Export format').select_option('print')
 files.get_by_role('button',name='Prepare fixed export',exact=True).click()
 files.get_by_role('button',name='Open clean print view').click()
 expect(files.get_by_role('status').last).to_contain_text('Clean print view ready')
 frame=page.frame_locator('iframe')
 expect(frame.get_by_role('heading',name='稿件 <script>')).to_be_visible()
 assert page.evaluate('window.pwned') is None
 assert frame.locator('script,img,style:not(head style)').count()==0
 assert frame.locator('[onclick]').count()==0
 assert 'allow-scripts' not in files.locator('iframe').get_attribute('sandbox')
 assert not page.evaluate("calls.some(c=>c.tail?.includes('pdf'))")
 page.evaluate("() => {window.printCount=0;document.querySelector('iframe').contentWindow.print=()=>{window.printCount++;};}")
 files.get_by_role('button',name='Open browser print dialog').click()
 assert page.evaluate('window.printCount')==1
 expect(files.get_by_role('status').last).to_contain_text('Printing or saving as PDF is not confirmed')
 # Identity changes abort pending preparation: an old read ACK cannot launch a new export POST.
 files.get_by_label('Manuscript / version').select_option(label='Working screenplay')
 page.evaluate('delayResource=true')
 prior_exports=page.evaluate("calls.filter(c=>c.tail==='exports').length")
 files.get_by_role('button',name='Prepare fixed export',exact=True).click()
 page.wait_for_function('typeof releaseResource === "function"')
 page.evaluate("actor='actor-b';viewer=true;renderTools()")
 page.wait_for_timeout(50)
 page.evaluate('releaseResource();delayResource=false')
 page.wait_for_timeout(50)
 assert page.evaluate("calls.filter(c=>c.tail==='exports').length")==prior_exports
 # Identity changes remove all tool drafts; viewer can export/search but cannot mutate.
 page.get_by_role('button',name='Search & replace',exact=True).click()
 search=page.get_by_role('region',name='Search & replace')
 expect(search.get_by_label('Literal search text')).to_have_value('')
 search.get_by_label('Literal search text').fill('Keeper')
 search.get_by_role('button',name='Search selected scope').click()
 expect(search.get_by_role('checkbox',name='Select match: Keeper').first).to_be_disabled()
 # Semantic bilingual registration uses lane fragments only.
 page.evaluate("locale('zh-TW')")
 expect(page.get_by_role('button',name='搜尋與取代',exact=True)).to_be_visible()
 assert errors==[],errors
 assert external==[],external
 context.close();browser.close()
print('PASS: mounted React Bible/Search/Files interactions, stale/locked/auth boundaries, replay, import cancellation, private download and safe print, identity/viewer/i18n/focus')
`;

test('WritingToolsPanel mounted component behavior (Chromium, synthetic transport only)', {timeout:120000}, async () => {
  const directory=await mkdtemp(join(tmpdir(),'writing-tools-ui-'));
  let server;
  try {
    await build({stdin:{contents:fixture,resolveDir:new URL('..',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1'),loader:'jsx'},bundle:true,format:'esm',outfile:join(directory,'bundle.js'),loader:{'.js':'jsx'},logLevel:'silent'});
    server=createServer(async(req,res)=>{
      if(req.url==='/bundle.js'||req.url==='/bundle.css'){
        res.setHeader('Content-Type',req.url.endsWith('.css')?'text/css':'text/javascript');res.end(await readFile(join(directory,req.url.slice(1))));
      } else {res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="en"><head><link rel="stylesheet" href="/bundle.css"></head><body><div id="root"></div><script type="module" src="/bundle.js"></script></body></html>');}
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const output=await new Promise((resolve,reject)=>{
      const child=spawn(process.env.PYTHON || 'python',['-X','utf8','-c',driver],{env:{...process.env,WRITING_TOOLS_TEST_URL:`http://127.0.0.1:${server.address().port}`}});
      let stdout='',stderr='';child.stdout.on('data',chunk=>stdout+=chunk);child.stderr.on('data',chunk=>stderr+=chunk);child.on('error',reject);
      child.on('exit',code=>resolve({code,stdout,stderr}));
    });
    assert.equal(output.code,0,output.stdout+'\n'+output.stderr);
    assert.match(output.stdout,/PASS: mounted React/);
    console.log(output.stdout.trim());
  } finally {if(server)await new Promise(resolve=>server.close(resolve));await rm(directory,{recursive:true,force:true});}
});
