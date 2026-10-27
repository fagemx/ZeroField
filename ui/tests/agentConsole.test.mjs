import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {GROUPS,PAGES,TEMPLATES,STUDIO_TOOLS,AGENT_FIELDS,LIMIT_FIELDS,RESOURCE_FIELDS,agentInput,budgetRemaining,consoleError,consoleHash,consoleRoute,mergeSession,money,parseObject,quoteCurrent,resourceSearch} from '../src/agentConsole/model.js';
import {setLocale,t} from '../src/i18n/index.js';
import {normalizeStatus,statusLabel} from '../src/format.js';

test('Console owns exactly four groups/twelve lean stable wire IDs and twelve templates/thirteen offered tools (SPEC_20 R16 context tools, R27 propose_previs_ops)',()=>{
  assert.deepEqual(GROUPS,{workspace:['dashboard','api_keys'],build:['playground','skills'],managed_agents:['quickstart','agents','sessions','deployments','environments','memory_store'],analytics:['usage_cost','spend_rate_limits']});
  assert.equal(PAGES.length,12);assert.equal(new Set(TEMPLATES).size,12);assert.equal(STUDIO_TOOLS.length,13);
  for(const excluded of ['files','batches','service_accounts','webhooks','logs','cli'])assert.ok(!PAGES.includes(excluded));
});
test('hash routing preserves exact resource IDs, deep links, back routes and malformed input safety',()=>{
  assert.deepEqual(consoleRoute('#/agent-console'),{page:'dashboard',resource:''});
  for(const page of PAGES)assert.deepEqual(consoleRoute(consoleHash(page,'studio:open')),{page,resource:'studio:open'});
  assert.equal(consoleRoute('#cinema-studio~a12'),null);
  assert.deepEqual(consoleRoute('#/agent-console/sessions/%broken'),{page:'sessions',resource:''});
  assert.equal(consoleRoute('#/agent-console/excluded').page,'dashboard');
});
test('write projections do not materialize computed authority, secrets, counters or enterprise settings',()=>{
  const profile={agent_key:'custom',version:2,provider_config:{},effort:'high',read_only:false,effective_provider_config:{model:'derived'},owner_id:'not-authority',_PRINCIPAL:'forged'};
  assert.deepEqual(agentInput(profile),{agent_key:'custom',version:2,provider_config:{},effort:'high'});
  assert.ok(!AGENT_FIELDS.includes('effort_configured'));assert.ok(!LIMIT_FIELDS.includes('judge_trial_used_runs'));assert.ok(!LIMIT_FIELDS.includes('judge_trial_cap_runs'));
  for(const field of ['retention_policy','otel_config','webhooks','api_key','secret'])assert.ok(!LIMIT_FIELDS.includes(field));
  assert.deepEqual(RESOURCE_FIELDS.providers,['vault_key','version','display_name','provider_config','allowed_agent_keys','enabled']);
});
test('unknown/null costs remain unknown; pending-inclusive remaining never invents free money',()=>{
  assert.equal(budgetRemaining({spend_limit_monthly_usd:10,accounted_usd:null,unknown_price_operations:0}),null);
  assert.equal(budgetRemaining({spend_limit_monthly_usd:10,accounted_usd:3,unknown_price_operations:1}),null);
  assert.equal(budgetRemaining({spend_limit_monthly_usd:10,accounted_usd:12,unknown_price_operations:0}),0);
  assert.equal(budgetRemaining({spend_limit_monthly_usd:10,accounted_usd:3,unknown_price_operations:0}),7);
  assert.notEqual(money(null),money(0));assert.equal(money('NaN'),money(null));
});
test('expiry is strict across every quote; no forged missing expiry or client hard-bound inference',()=>{
  const now=100000;
  assert.equal(quoteCurrent({quotes:[{expires_at:new Date(now+1).toISOString(),hard_bound:false}]},now),true);
  for(const quotes of [[],[{}],[{expires_at:'bad'}],[{expires_at:new Date(now).toISOString()}],[{expires_at:new Date(now+1).toISOString()},{expires_at:new Date(now-1).toISOString()}]])assert.equal(quoteCurrent({quotes},now),false);
});
test('live cursor merge retains all message pages without duplicating IDs or stale task state',()=>{
  const a={messages:[{id:1},{id:2}],tasks:[{status:'running'}],cursor:'old'};
  const result=mergeSession(a,{messages:[{id:2},{id:3}],tasks:[{status:'succeeded'}],cursor:'new',has_more:false});
  assert.deepEqual(result.messages.map(m=>m.id),[1,2,3]);assert.equal(result.cursor,'new');assert.equal(result.tasks[0].status,'succeeded');assert.equal(a.messages.length,2);
});
test('all navigation/templates/badges/errors/consent are semantic bilingual; status display never changes wire logic',async()=>{
  const en=JSON.parse(await readFile(new URL('../src/i18n/locales/en.json',import.meta.url)));
  const zh=JSON.parse(await readFile(new URL('../src/i18n/locales/zh-TW.json',import.meta.url)));
  const flatten=(value,prefix='')=>Object.entries(value).flatMap(([key,item])=>typeof item==='object' ? flatten(item,prefix+key+'.'):[prefix+key]);
  assert.deepEqual(flatten(en.console).sort(),flatten(zh.console).sort());
  for(const locale of ['en','zh-TW']){await setLocale(locale);
    for(const page of PAGES)assert.notEqual(t('console.pages.'+page),'console.pages.'+page);
    for(const key of TEMPLATES)for(const field of ['title','description'])assert.ok(t('console.templates.'+key+'.'+field).length>4);
    assert.equal(normalizeStatus('succeeded'),'succeeded');assert.notEqual(statusLabel('succeeded'),'succeeded');
    assert.ok(consoleError({status:409}).length>30);assert.ok(consoleError({status:409,data:{error:'Judge cap; secret DO_NOT_ECHO'}}).length>30);assert.ok(!consoleError({status:409,data:{error:'Judge cap; secret DO_NOT_ECHO'}}).includes('DO_NOT_ECHO'));
  }await setLocale('en');
});
test('resource search finds pages and actual catalog resources without mutating custom labels',()=>{
  const catalog={agents:[{agent_key:'custom',display_name:'Original 自訂 name'}],sessions:[{id:'run-1',objective:'Inspect optics'}]};
  assert.equal(resourceSearch(catalog,'Original')[0].resource,'custom');assert.equal(resourceSearch(catalog,'optics')[0].page,'sessions');assert.equal(catalog.agents[0].display_name,'Original 自訂 name');assert.equal(resourceSearch({},'')[0].page,'dashboard');
  const deployments=resourceSearch({deployments:[{deployment_key:'nightly',agent_key:'coordinator'},{deployment_key:'weekly',agent_key:'coordinator'}]},'').filter(e=>e.resource).map(e=>e.resource);assert.deepEqual(deployments,['nightly','weekly']);
  for(const text of ['[]','null','false','42','broken'])assert.throws(()=>parseObject(text));
});
