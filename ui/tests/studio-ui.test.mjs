import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

let components, temporary;
const uiRoot=resolve(dirname(fileURLToPath(import.meta.url)),'..');
before(async()=>{
  temporary=await mkdtemp(join(uiRoot,'tests/.studio-render-'));
  const result=await build({stdin:{contents:"export {MediaCell} from './src/MediaCell.jsx'; export {SheetReview} from './src/SheetReview.jsx'; export {SheetCards} from './src/SheetCards.jsx'; export {ProposalRaceView} from './src/assistant/ProposalRaceView.jsx'; export {ShotBench} from './src/ShotBench.jsx';",resolveDir:uiRoot,sourcefile:'studio-render.jsx',loader:'jsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',external:['react','react/*','react-dom','react-dom/*'],loader:{'.css':'empty'}});
  const output=join(temporary,'components.mjs');await writeFile(output,result.outputFiles[0].text);components=await import(pathToFileURL(output));
});
after(async()=>{if(temporary){assert.ok(temporary.startsWith(join(uiRoot,'tests','.studio-render-')));await rm(temporary,{recursive:true,force:true});}});
const render=(Component,props)=>renderToStaticMarkup(React.createElement(Component,props));

test('full and compact media cells render inline video, and a full take exposes regeneration',()=>{
  const value='[video](https://example.org/shot.mp4)';
  const full=render(components.MediaCell,{value,onRegenerate:()=>{}}),compact=render(components.MediaCell,{value,compact:true});
  assert.match(full,/<video[^>]+controls=""/);assert.match(full,/preload="metadata"/);assert.match(full,/Re-shoot Take/);
  assert.match(compact,/<video/);assert.doesNotMatch(compact,/controls=""/);assert.doesNotMatch(compact,/Video attachment/);
});

test('race candidates render parallel playable video takes',()=>{
  const gate={title:'Choose a take',proposals:[{id:'p1',agent_key:'a',content:'[video](https://example.org/a.mp4)'},{id:'p2',agent_key:'b',content:'[video](https://example.org/b.mp4)'}]};
  const html=render(components.ProposalRaceView,{gate,onSelect:()=>{},onClose:()=>{}});
  assert.equal((html.match(/class="race-video"/g)||[]).length,2);assert.equal((html.match(/controls=""/g)||[]).length,2);
});

test('review is a non-modal dialog and leaves keyboard focus available to the Assistant',()=>{
  const html=render(components.SheetReview,{onClose:()=>{},onStep:()=>{},children:React.createElement('button',null,'Close')});
  assert.match(html,/role="dialog"/);assert.match(html,/aria-modal="false"/);
});

test('cards render source and output stages with upload and run actions',()=>{
  const row={rid:'r1',cells:[{value:'Shot 1'}]},parsed={headers:['Shot','Source','Take'],rows:[row],table:{attrs:{column_types:['text','video','video']}}};
  const model={coverColumn:1,groupColumn:-1,cards:[{row,index:0,title:'Shot 1',summary:[],mediaChain:[{column:1,label:'Source',type:'video',value:'[video](https://example.org/source.mp4)',media:{kind:'video'}},{column:2,label:'Take',type:'video',value:'',media:null}],assets:[{id:'CAST-01',value:'![cast](https://example.org/cast.png)',type:'image'}]}]};
  const html=render(components.SheetCards,{model,mode:'gallery',parsed,selected:new Set(),writable:true});
  assert.match(html,/sheet-card-chain/);assert.match(html,/<video/);assert.match(html,/No media yet/);assert.match(html,/@CAST-01/);assert.match(html,/>Run<\/button>/);
});

test('opening Assistant preserves review and row panels; annotation clicks open the stable row',async()=>{
  const workspace=await readFile(join(uiRoot,'src/SheetWorkspace.jsx'),'utf8'),app=await readFile(join(uiRoot,'src/App.jsx'),'utf8');
  assert.match(workspace,/if\(assistantOpen\)\{setRequest\(null\);setPanel\(current=>current==='columns'\?null:current\);\}/);
  assert.match(workspace,/if\(focusRow.openRow\)\{setRowOpen\(focusRow.rowId\);setPanel\('row'\)/);
  assert.doesNotMatch(app,/onPanelChange=\{onSurfacePanel\}/);
  assert.match(app,/openRow:true/);
});

test('Micro review displays bound assets and edits prompts with the guarded cell draft',async()=>{
  const source=await readFile(join(uiRoot,'src/SheetWorkspace.jsx'),'utf8');
  assert.match(source,/previewAssets=previewRow\?assetReferences\(previewRow\)/);
  assert.match(source,/<ShotBench stages=\{rowMediaCols\} assets=\{previewAssets\}/);
  const bench=await readFile(join(uiRoot,'src/ShotBench.jsx'),'utf8');
  assert.match(bench,/className="bench-assets" aria-label=\{uiText\('studio.boundAssets'\)\}/);
  assert.match(source,/onClick=\{\(\)=>beginEdit\(preview.r,c\)\}/);
  assert.match(source,/<textarea ref=\{editor\} aria-label=\{parsed.headers\[c\]\} rows=\{4\} value=\{text\}/);
  assert.match(source,/onChange=\{event=>setText\(event.target.value\)\}/);
  assert.match(source,/if\(!previewTargetValid\|\|!guardDraft\(\)\)return/);
  assert.match(source,/const closePanel=\(\)=>\{if\(!guardDraft\(\)\)return/);
});

test('generated output takes offer a take bundle download; inputs and external media do not',()=>{
  const asset='/projects/api/film/assets/pa_'+'a'.repeat(32);
  const stage=(column,label,url)=>({column,label,type:'video',value:`[video](${url})`,media:{url,kind:'video'}});
  const html=render(components.ShotBench,{stages:[stage(2,'Source Driving Video',asset),stage(5,'Cinema Shot',asset)],assets:[],writable:false,onBundle:()=>{}});
  assert.equal(html.match(/Download take bundle/g)?.length,1);
  assert.match(html,/class="bench-bundle"/);
  assert.doesNotMatch(render(components.ShotBench,{stages:[stage(5,'Cinema Shot','https://example.com/take.mp4')],assets:[],onBundle:()=>{}}),/Download take bundle/);
  assert.doesNotMatch(render(components.ShotBench,{stages:[stage(5,'Cinema Shot',asset)],assets:[]}),/Download take bundle/);
});

test('sheet workspace wires per-take bundles and the approved-takes export to authenticated endpoints',async()=>{
  const source=await readFile(join(uiRoot,'src/SheetWorkspace.jsx'),'utf8');
  assert.match(source,/onBundle=\{stage=>run\(\(\)=>api\.download\(`\$\{stage\.media\.url\}\/bundle`/);
  assert.match(source,/api\.download\(`\/projects\/api\/\$\{slug\}\/takes\/export`/);
  for(const name of ['en','zh-TW']){
    const locale=JSON.parse(await readFile(join(uiRoot,`src/i18n/locales/${name}.json`),'utf8'));
    assert.ok(locale.studio.downloadTakeBundle&&locale.studio.takeBundleHint&&locale.sheetWorkspace.exportApprovedTakes,name);
  }
});
