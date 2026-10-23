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
 const output=await build({stdin:{contents:"export{i18n}from'./src/i18n/index.js';export{WritingPreview}from'./src/writing/WritingPreview.jsx';export{WritingOutline}from'./src/writing/WritingOutline.jsx';export{WritingVersions}from'./src/writing/WritingVersions.jsx';export{canonicalEditorDoc}from'./src/writing/WritingEditor.jsx';",resolveDir:uiRoot,loader:'jsx'},bundle:true,write:false,format:'esm',platform:'node',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
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
test('generic frozen impact UI defaults to no manual overwrite and does not expose destructive shot deletion',()=>{
 const preview={previewId:'p',kind:'impact',version:1,status:'pending',expiresAt:Date.now()/1000+120,allowedActions:[{actionId:'u',kind:'update_text',shotId:'shot1',fields:['dialogue']},{actionId:'k',kind:'keep_shot',shotId:'shot1'}],proposedChanges:[{shotId:'shot1',manualOverride:true,currentText:'Director text',suggestedText:'Suggested text',media:true}],warnings:[]};
 const html=render(components.WritingPreview,{preview,writable:true});assert.match(html,/Director override detected/);assert.match(html,/Director text/);assert.match(html,/Suggested text/);assert.match(html,/preserved/);assert.doesNotMatch(html,/checked=""/);assert.doesNotMatch(html,/Delete shot/);
});
test('snapshot catalog is read-only to viewers while compare remains visible',()=>{
 const html=render(components.WritingVersions,{workspace:{versions:{items:[{versionId:'v',name:'Final',locked:true,catalogVersion:1}]},branches:{items:[]}},resourceRef:{kind:'working'},writable:false,resource:()=>({docHash:'h'})});assert.match(html,/Compare with working screenplay/);assert.doesNotMatch(html,/Save named version/);assert.doesNotMatch(html,/>Unlock</);
});
test('editor canonicalization preserves bids, marks and table metadata without unwanted link defaults',()=>{
 const input={type:'doc',content:[{type:'paragraph',attrs:{bid:'b1',owner:null,created:null},content:[{type:'text',text:'Rich',marks:[{type:'bold'},{type:'link',attrs:{href:'https://example.org',target:'_blank',rel:'noopener'}}]}]},{type:'table',attrs:{bid:'bt',owner:null,created:null,column_ids:['c1'],column_options:{c1:{options:['A']}},mapping_revision:4,worksheet_name:null},content:[]}]};const actual=components.canonicalEditorDoc(input);assert.deepEqual(actual.content[0].attrs,input.content[0].attrs);assert.deepEqual(actual.content[0].content[0].marks,[{type:'bold'},{type:'link',attrs:{href:'https://example.org'}}]);assert.deepEqual(actual.content[1].attrs.column_ids,['c1']);assert.equal(actual.content[1].attrs.mapping_revision,4);assert.deepEqual(components.canonicalEditorDoc({type:'doc'}),{type:'doc',content:[]});
});
