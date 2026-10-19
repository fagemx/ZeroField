import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {join,dirname,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {t,setLocale} from '../src/i18n/index.js';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
let temporary, components;
before(async()=>{
  temporary=await mkdtemp(join(root,'tests/.story-render-'));
  const result=await build({stdin:{contents:"export {StoryWorkbench,ShotProduction,StoryBatchBar} from './src/StoryWorkbenchModals.jsx'; export {SheetCards} from './src/SheetCards.jsx';",resolveDir:root,sourcefile:'story-render.jsx',loader:'jsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
  const output=join(temporary,'components.mjs');await writeFile(output,result.outputFiles[0].text);components=await import(pathToFileURL(output));
});
after(async()=>{if(temporary)await rm(temporary,{recursive:true,force:true});});
const render=(name,props)=>renderToStaticMarkup(React.createElement(components[name],props));

test('all five workbench entries render and viewers cannot start creation',()=>{
  const html=render('StoryWorkbench',{slug:'demo',me:{can_write:false},tab:{key:'cinema-studio'}});
  for(const name of ['Start Creating','My Projects','Asset Vault','Toolbox','Open API']) assert.ok(html.includes(name));
  assert.match(html,/<button disabled="">✦ Start Creating/);
});

test('Micro has real candidate, split, restoration and node-input surfaces',()=>{
  const html=render('ShotProduction',{slug:'demo',rid:'brow',writable:true});
  for(const text of ['Candidate Takes','Split Shot','2nd-Pass 4K Restore','nodeInfoList','Re-shoot with These Inputs']) assert.ok(html.includes(text));
  assert.match(html,/<details>/);
});

test('scene headers are collapsible, counted and retain the rebuild action',()=>{
  const row={rid:'brow',cells:[{value:'SC01-S01'}]};
  const card={row,index:0,title:'SC01-S01',summary:[],assets:[],mediaChain:[]};
  const html=render('SheetCards',{model:{sceneGroups:[{key:'SC01',cards:[card]}],groupColumn:-1,coverColumn:-1},mode:'gallery',selected:new Set(),parsed:{headers:['Shot'],rows:[row],table:{attrs:{}}},writable:true,scenes:[{sceneIndex:1,sceneId:'sc_demo_01_S01',title:'Observatory Arrival'}]});
  assert.match(html,/<details open=""/);assert.match(html,/Observatory Arrival/);assert.match(html,/1 Shots/);assert.match(html,/Rebuild Scene Shots/);
});

test('new count and usage labels interpolate in both interface languages',async()=>{
  for(const locale of ['en','zh-TW']){
    await setLocale(locale);
    assert.ok(t('story.generateSelected',{count:3}).includes('3'));
    assert.doesNotMatch(t('story.assetUses',{shots:7,scenes:2}),/[{}]/);
  }
  await setLocale('en');
});
