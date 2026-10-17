import test from 'node:test';
import assert from 'node:assert/strict';
import * as imports from '../src/importModel.js';

test('confirmed import preserves target revision and selected header without mixing previews',()=>{
  assert.equal(typeof imports.importPath,'function');
  const path=imports.importPath('demo',{key:'t-abc',revision:7},{format:'xlsx',worksheet:'資料 & 成效',headerRow:3,deliveryMode:'new_workbook',confirmReplace:true});
  const url=new URL(path,'http://localhost');
  assert.equal(url.pathname,'/projects/api/demo/tabs/import');
  assert.equal(url.searchParams.get('base_revision'),'7');
  assert.equal(url.searchParams.get('worksheet'),'資料 & 成效');
  assert.equal(url.searchParams.get('header_row'),'3');
  assert.equal(url.searchParams.get('delivery_mode'),'new_workbook');
  assert.equal(url.searchParams.get('confirm_replace'),'true');
});
test('import rejects impossible header rows and never adds target parameters for new pages',()=>{
  assert.equal(typeof imports.importPath,'function');
  assert.throws(()=>imports.importPath('demo',null,{format:'csv',headerRow:0}),/表頭/);
  assert.throws(()=>imports.importPath('demo',null,{format:'csv',headerRow:1.5}),/表頭/);
  const url=new URL(imports.importPath('demo',null,{format:'md',headerRow:9}),'http://localhost');
  assert.equal(url.searchParams.has('header_row'),false);
  assert.equal(url.searchParams.has('tab_key'),false);
});
test('replacement requires explicit confirmation but read-only preview never does',()=>{
  assert.throws(()=>imports.importPath('demo',{key:'t',revision:7},{format:'csv',headerRow:3}),/確認/);
  assert.equal(typeof imports.importPreviewPath,'function');
  const url=new URL(imports.importPreviewPath('demo',{key:'t',revision:7},{format:'csv',headerRow:3}),'http://localhost');
  assert.equal(url.pathname,'/projects/api/demo/tabs/import-preview');
  assert.equal(url.searchParams.get('base_revision'),'7');
  assert.equal(url.searchParams.get('header_row'),'3');
  assert.equal(url.searchParams.has('confirm_replace'),false);
});
