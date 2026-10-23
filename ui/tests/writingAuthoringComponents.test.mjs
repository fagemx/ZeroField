import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
import { mkdtemp,writeFile,rm } from 'node:fs/promises';
import { join,resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const uiRoot=fileURLToPath(new URL('..',import.meta.url));
import en from '../src/writing/locales/authoring.en.json' with {type:'json'};
import zh from '../src/writing/locales/authoring.zh-TW.json' with {type:'json'};
let components,temp;
before(async()=>{
 temp=await mkdtemp(join(uiRoot,'tests/.writing-render-'));
 const output=await build({stdin:{contents:"export{i18n}from'./src/i18n/index.js';export{WritingPreview}from'./src/writing/WritingPreview.jsx';export{WritingMaterializationChanges}from'./src/writing/WritingMaterializationChanges.jsx';export{WritingOutline}from'./src/writing/WritingOutline.jsx';export{WritingVersions}from'./src/writing/WritingVersions.jsx';export{canonicalEditorDoc}from'./src/writing/WritingEditor.jsx';",resolveDir:uiRoot,loader:'jsx'},bundle:true,write:false,format:'esm',platform:'node',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
 const path=join(temp,'components.mjs');await writeFile(path,output.outputFiles[0].text);components=await import(pathToFileURL(path));
 components.i18n.addResourceBundle('en','translation',{writing:{authoring:en}},true,true);components.i18n.addResourceBundle('zh-TW','translation',{writing:{authoring:zh}},true,true);
});
after(async()=>{if(temp)await rm(temp,{recursive:true,force:true});});
const render=(Component,props)=>renderToStaticMarkup(React.createElement(Component,props));
test('owned fragments are flat semantic payloads with identical nonempty messages and placeholders',()=>{
 assert.deepEqual(Object.keys(en).sort(),Object.keys(zh).sort());for(const key of Object.keys(en)){assert.equal(typeof en[key],'string',key);assert.ok(zh[key]?.trim(),key);const parameters=text=>[...text.matchAll(/\{\{(\w+)\}\}/g)].map(match=>match[1]).sort();assert.deepEqual(parameters(en[key]),parameters(zh[key]),key);}
});
test('core numeric-expiry/object-proposedChanges previews render real text and exact adopt actions',()=>{
 const preview={previewId:'p',kind:'promotion',version:1,status:'pending',expiresAt:Date.now()/1000+120,allowedActions:[{actionId:'whole',kind:'adopt_whole'}],proposedChanges:{doc:{type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'A changed ending.'}]}]},sourceDoc:{type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'A changed ending.'}]}]}},warnings:[]};
 const html=render(components.WritingPreview,{preview,writable:true});assert.match(html,/A changed ending/);assert.match(html,/Adopt whole manuscript/);assert.doesNotMatch(html,/stale, expired/);assert.doesNotMatch(html,/checked=""/);assert.match(html,/disabled=""[^>]*>Apply selected content/);
});
test('synthetic promotion visibly discloses selected authored-scene materialization without changing source prose',()=>{
 const text=value=>({type:'text',text:value});const sourceDoc={type:'doc',content:[{type:'heading',attrs:{bid:'canonical',level:2},content:[text('Scene 01: Corrected chapter')]},{type:'paragraph',attrs:{bid:'original'},content:[{...text('> Scene 01: Repeat'),marks:[{type:'bold'}]},{type:'hardBreak'},text('Original action <script> stays text.')]},{type:'heading',attrs:{bid:'other-heading',level:2},content:[text('Unselected conversion text')]},{type:'paragraph',attrs:{bid:'other-body'},content:[text('Unselected body')]}]};
 const materialization={sceneKey:'selected-scene',kind:'materialize_authored_scene',headingBid:'canonical',headingText:'Scene 01: Corrected chapter',quotedBlockBids:['original'],source:{docHash:'original-source-hash',headingBid:null,blockBids:['original'],title:'Corrected chapter'}};
 const preview={previewId:'p',kind:'promotion',version:1,status:'pending',expiresAt:Date.now()/1000+120,allowedActions:[{actionId:'adopt:selected-scene',kind:'adopt_scene',sceneKey:'selected-scene'}],proposedChanges:{whole:false,doc:{type:'doc',content:[]},sourceDoc,sourceStructure:{scenes:[{sceneKey:'selected-scene',headingBid:'canonical',blockBids:['original']},{sceneKey:'unselected-scene',headingBid:'other-heading',blockBids:['other-body']}]},materializationChanges:[materialization]},warnings:['Adoption materializes authored scene headings and visibly quotes original Scene lines.']};
 const before=JSON.stringify(preview),html=render(components.WritingPreview,{preview,writable:true});assert.match(html,/Mainline compatibility conversion/);assert.match(html,/Corrected chapter/);assert.match(html,/Scene 01: Corrected chapter/);assert.match(html,/original-source-hash/);assert.match(html,/Quoted source block original/);assert.match(html,/&gt; Scene 01: Repeat/);assert.match(html,/Original branch\/version prose stays unchanged/);assert.match(html,/Not selected for apply/);assert.doesNotMatch(html,/Unselected conversion text|Unselected body|<script>/);assert.equal(JSON.stringify(preview),before);
 const chosen=render(components.WritingMaterializationChanges,{proposal:preview.proposedChanges,actions:preview.allowedActions,selected:[{actionId:'adopt:selected-scene',kind:'adopt_scene'}]});assert.match(chosen,/Selected for this apply/);
});
test('synthetic frozen impact v1 UI shows actual alignment/provenance and defaults to no manual overwrite',()=>{
 const preview={previewId:'p',kind:'impact',version:1,status:'pending',expiresAt:Date.now()/1000+120,allowedActions:[{actionId:'u',kind:'update_text',shotId:'shot1',fields:['dialogue']},{actionId:'k',kind:'keep_shot',shotId:'shot1'}],proposedChanges:{shots:[{shotId:'shot1',shotIndex:'SC01-S01',sourceRef:{sceneKey:'scene1',beatKey:'beat1'},storyOrigin:{versionId:'origin-old'},storyAlignment:{state:'manual_override',reasons:['source_changed'],manualFields:['description'],mediaOutdated:true},current:{description:'Director text',dialogue:[]},suggested:{description:'Suggested text',dialogue:[]},oldSource:[],newSource:[],media:{selectedVideoUrl:'/private/old-take.mp4'},actionIds:['u','k']}],additions:[{description:'New text shot'}],assetChanges:[{name:'New prop'}],confirmBaseline:true,targetVersionId:null,canApply:true},warnings:[]};
 const html=render(components.WritingPreview,{preview,writable:true});assert.match(html,/Director override detected/);assert.match(html,/Director text/);assert.match(html,/Suggested text/);assert.match(html,/preserved/);assert.doesNotMatch(html,/checked=""/);assert.doesNotMatch(html,/Delete shot/);assert.match(html,/origin-old/);assert.match(html,/earlier or uncertain screenplay/);assert.match(html,/New prop/);assert.match(html,/New text shot/);assert.match(html,/preload="metadata"/);
});
test('synthetic additive row freshness warns without blanket disabling unrelated actions; legacy/shared stale disables',()=>{
 const preview={previewId:'p',kind:'impact',version:1,status:'pending',expiresAt:Date.now()/1000+120,allowedActions:[{actionId:'keep1',kind:'keep_shot',shotId:'shot1'},{actionId:'keep2',kind:'keep_shot',shotId:'shot2'}],proposedChanges:{shots:[],additions:[],assetChanges:[],confirmBaseline:false,canApply:true},warnings:[],stale:true,sharedStale:false,staleActionIds:['keep2']};
 const html=render(components.WritingPreview,{preview,writable:true});assert.match(html,/Some frozen shot actions changed/);assert.doesNotMatch(html,/<fieldset disabled/);assert.match(html,/Changed row/);assert.match(render(components.WritingPreview,{preview:{...preview,sharedStale:true},writable:true}),/<fieldset disabled/);const {sharedStale,staleActionIds,...legacy}=preview;assert.match(render(components.WritingPreview,{preview:legacy,writable:true}),/<fieldset disabled/);
});
test('snapshot catalog is read-only to viewers while compare remains visible',()=>{
 const html=render(components.WritingVersions,{workspace:{versions:{items:[{versionId:'v',name:'Final',locked:true,catalogVersion:1}]},branches:{items:[]}},resourceRef:{kind:'working'},writable:false,resource:()=>({docHash:'h'})});assert.match(html,/Compare with working screenplay/);assert.doesNotMatch(html,/Save named version/);assert.doesNotMatch(html,/>Unlock</);
});
test('editor canonicalization preserves bids, marks and table metadata without unwanted link defaults',()=>{
 const input={type:'doc',content:[{type:'paragraph',attrs:{bid:'b1',owner:null,created:null},content:[{type:'text',text:'Rich',marks:[{type:'bold'},{type:'link',attrs:{href:'https://example.org',target:'_blank',rel:'noopener'}}]}]},{type:'table',attrs:{bid:'bt',owner:null,created:null,column_ids:['c1'],column_options:{c1:{options:['A']}},mapping_revision:4,worksheet_name:null},content:[]}]};const actual=components.canonicalEditorDoc(input);assert.deepEqual(actual.content[0].attrs,input.content[0].attrs);assert.deepEqual(actual.content[0].content[0].marks,[{type:'bold'},{type:'link',attrs:{href:'https://example.org'}}]);assert.deepEqual(actual.content[1].attrs.column_ids,['c1']);assert.equal(actual.content[1].attrs.mapping_revision,4);assert.deepEqual(components.canonicalEditorDoc({type:'doc'}),{type:'doc',content:[]});
});
