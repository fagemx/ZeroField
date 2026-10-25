import test from 'node:test';
import assert from 'node:assert/strict';
import { i18n, t, normalizeLocale, localeFromCookie, setLocale } from '../src/i18n/index.js';
import { normalizeStatus, statusLabel, statusClass, roleLabel, agentLabel } from '../src/format.js';
import { progressCounts } from '../src/assistant/text.js';
import { statusMovePayload } from '../src/sheetViews.js';
import { tablesOf } from '../src/sheetModel.js';
import { errorMessage } from '../src/api.js';
import en from '../src/i18n/locales/en.json' with {type:'json'};
import zh from '../src/i18n/locales/zh-TW.json' with {type:'json'};

test('English is the default; only explicitly supported locale preferences are accepted', () => {
  assert.equal(i18n.language, 'en');
  assert.equal(normalizeLocale('zh-TW'), 'zh-TW');
  for (const value of [undefined, '', 'zh-CN', 'fr', '<script>', '__proto__']) assert.equal(normalizeLocale(value), 'en');
  assert.equal(localeFromCookie('session=private; zerofield_locale=zh-TW'), 'zh-TW');
  assert.equal(localeFromCookie('zerofield_locale=%'), 'en');
});

test('locale switching translates labels while normalized wire values, colors and progress remain stable', async () => {
  await setLocale('zh-TW');
  assert.equal(t('common.save'), '儲存');
  assert.equal(statusLabel('Pending Review'), '待審核');
  assert.equal(statusLabel('已完成'), '已核准');
  assert.equal(normalizeStatus('已完成'), 'Approved');
  assert.equal(normalizeStatus('Pending Review'), 'Pending Review');
  assert.equal(statusClass('已完成'), 'done');
  assert.equal(statusLabel('Custom delivery'), 'Custom delivery');
  assert.equal(progressCounts([{kind:'question',status:'Approved'},{kind:'handoff',status:'已完成'}]).questionsDone, 1);
  await setLocale('en');
  assert.equal(statusLabel('已完成'), 'Approved');
});

test('missing Traditional Chinese messages fall back to English and interpolation preserves user text', async () => {
  i18n.addResource('en', 'translation', 'test.fallback', 'Hello {{name}}');
  await setLocale('zh-TW');
  assert.equal(t('test.fallback', {name:'Kael <original>'}), 'Hello Kael <original>');
  await setLocale('en');
  delete i18n.getResourceBundle('en', 'translation').test;
});

test('both dictionaries cover the same messages and interpolation parameters', () => {
  const visit = (left, right, path = '') => {
    assert.deepEqual(Object.keys(left).sort(), Object.keys(right).sort(), path);
    for (const [key, value] of Object.entries(left)) {
      const name = path ? `${path}.${key}` : key;
      if (typeof value === 'object' && value !== null) { assert.equal(typeof right[key], 'object', name); visit(value, right[key], name); continue; }
      assert.equal(typeof value, 'string', name); assert.equal(typeof right[key], 'string', name);
      const params = text => [...new Set([...text.matchAll(/\{\{(\w+)\}\}/g)].map(m=>m[1]))].sort();
      assert.ok(right[key].trim(), name);
      assert.deepEqual(params(value), params(right[key]), name);
    }
  };
  visit(en, zh);
});

test('legacy status moves preserve wire values and custom names remain unchanged in Chinese', async () => {
  const text = value => ({type:'text',text:value});
  const cell = content => ({type:'tableCell',content:[{type:'paragraph',content}]});
  const doc = {type:'doc',content:[{type:'table',attrs:{bid:'b_table',column_ids:['c_status'],column_types:['status'],column_options:{c_status:{options:['Approved']}}},content:[
    {type:'tableRow',attrs:{bid:'r_header'},content:[{type:'tableHeader',content:[{type:'paragraph',content:[text('Status')]}]}]},
    {type:'tableRow',attrs:{bid:'r_body'},content:[cell([{type:'status',attrs:{fid:'f_status',label:'已完成'}}])]},
  ]}]};
  const parsed = tablesOf(doc, {})[0];
  const before = JSON.stringify(doc);
  await setLocale('zh-TW');
  const payload = statusMovePayload(parsed, 'r_body', 0, '已完成');
  assert.equal(payload.row_edits[0].cells[0], '已完成');
  assert.equal(JSON.stringify(doc), before);
  assert.equal(roleLabel('director'), '導演');
  assert.equal(agentLabel({agent_key:'coordinator',display_name:'Showrunner'}), '製片總監');
  assert.equal(agentLabel({agent_key:'coordinator',display_name:'My Director'}), 'My Director');
  assert.equal(errorMessage({message_key:'errors.unknown'}, 'Provider failed'), 'Provider failed');
  const key = Object.keys(en.errors).find(k=>en.errors[k]==='Read-only crew members cannot modify a production.');
  assert.equal(errorMessage({message_key:'errors.'+key}, 'English fallback'), zh.errors[key]);
  await setLocale('en');
});
