import test from 'node:test';
import assert from 'node:assert/strict';
import {storyRequest} from '../src/storyModel.js';
import {ApiError} from '../src/api.js';
import en from '../src/i18n/locales/en.json' with {type:'json'};
import zh from '../src/i18n/locales/zh-TW.json' with {type:'json'};
import authoring from '../src/writing/locales/authoring.en.json' with {type:'json'};
import authoringZh from '../src/writing/locales/authoring.zh-TW.json' with {type:'json'};
import reviewAuthoring from '../src/writing/locales/review1-authoring.en.json' with {type:'json'};
import reviewAuthoringZh from '../src/writing/locales/review1-authoring.zh-TW.json' with {type:'json'};
import reviewAuth from '../src/writing/locales/review1-auth.en.json' with {type:'json'};
import reviewAuthZh from '../src/writing/locales/review1-auth.zh-TW.json' with {type:'json'};
import tools from '../src/writing/locales/tools.en.json' with {type:'json'};
import toolsZh from '../src/writing/locales/tools.zh-TW.json' with {type:'json'};

test('Story transport preserves replay keys, binary/raw bodies and structured errors on GET as well as writes',async()=>{
  const original=globalThis.fetch, calls=[];
  try {
    globalThis.fetch=async(path,options)=>{calls.push({path,options});return new Response(JSON.stringify({code:0,data:{ok:true}}),{headers:{'Content-Type':'application/json'}});};
    const body={clientMutationId:'same',baseVersion:1};
    await storyRequest('/episodes/e/writing/compare','POST',body,{idempotencyKey:'one-action'});
    await storyRequest('/episodes/e/writing/compare','POST',body,{idempotencyKey:'one-action'});
    assert.equal(calls[0].options.headers.get('Idempotency-Key'),'one-action');
    assert.equal(calls[1].options.body,calls[0].options.body);
    const raw=new Uint8Array([0,255,5]);
    await storyRequest('/episodes/e/writing/imports','POST',raw,{raw:true,idempotencyKey:'upload',headers:{'X-Filename':'novel.docx'}});
    assert.equal(calls.at(-1).options.body,raw);assert.equal(calls.at(-1).options.headers.has('Content-Type'),false);
    globalThis.fetch=async()=>new Response('private bytes');
    assert.equal(await storyRequest('/content','GET',undefined,{responseType:'text'}),'private bytes');
    assert.equal(await (await storyRequest('/content','GET',undefined,{responseType:'blob'})).text(),'private bytes');
    globalThis.fetch=async()=>new Response(JSON.stringify({code:'DRAMA_WRITING_CONFLICT',message:'Changed',details:{resource:'authorized'}}),{status:409});
    await assert.rejects(()=>storyRequest('/workspace'),error=>error instanceof ApiError&&error.status===409&&error.code==='DRAMA_WRITING_CONFLICT'&&error.details.resource==='authorized'&&error.data.message==='Changed');
  } finally {globalThis.fetch=original;}
});
test('both product dictionaries contain the exact component fragments without flattened or overwritten leaves',()=>{
 assert.equal(Object.keys(authoring).some(key=>Object.hasOwn(reviewAuthoring,key)),false,'repair fragment must not overwrite original authoring leaves');
 assert.deepEqual(en.writing.authoring,{...authoring,...reviewAuthoring});assert.deepEqual(zh.writing.authoring,{...authoringZh,...reviewAuthoringZh});
 assert.deepEqual(en.writing.reviewIdentity,reviewAuth.writing.reviewIdentity);assert.deepEqual(zh.writing.reviewIdentity,reviewAuthZh.writing.reviewIdentity);
 assert.deepEqual(en.writing.tools,tools);assert.deepEqual(zh.writing.tools,toolsZh);
});
