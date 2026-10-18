import test from 'node:test';
import assert from 'node:assert/strict';
import { openReplies, resolveAgentTarget, agentSuggestions, messagePersona } from '../src/assistant/agentModel.js';

const agents = [
  {agent_key:'coordinator',display_name:'專案總編排',enabled:true,role_kind:'primary',runtime_kind:'builtin_llm'},
  {agent_key:'doc_writer',display_name:'企劃與劇本代理',enabled:true,role_kind:'worker',runtime_kind:'builtin_llm'},
  {agent_key:'sheet_ops',display_name:'表格與分鏡量產代理',enabled:true,role_kind:'worker',runtime_kind:'builtin_llm'},
  {agent_key:'off',display_name:'停用',enabled:false,role_kind:'worker',runtime_kind:'builtin_llm'},
];

test('other agent running does not block selected agent', () => {
  const busy = openReplies([{id:1,role:'assistant',agent_key:'doc_writer',status:'running'},
                            {id:2,role:'assistant',agent_key:'sheet_ops',status:'done'}]);
  assert.equal(busy.has('doc_writer'),true);
  assert.equal(busy.has('sheet_ops'),false);
});

test('mention routing ignores email quoted text code and member tokens', () => {
  for (const text of ['hello','mail@example.com','`@doc_writer`','> @doc_writer\nhello','@{11111111-1111-4111-8111-111111111111}']) {
    assert.equal(resolveAgentTarget(text,null,agents),'coordinator');
  }
  assert.equal(resolveAgentTarget('@doc_writer 請整理',null,agents),'doc_writer');
  assert.equal(resolveAgentTarget('@表格與分鏡量產代理 請核對',null,agents),'sheet_ops');
  assert.throws(()=>resolveAgentTarget('@doc_writer @sheet_ops',null,agents));
  assert.throws(()=>resolveAgentTarget('@doc_writer','sheet_ops',agents));
  assert.throws(()=>resolveAgentTarget('@off',null,agents));
  assert.throws(()=>resolveAgentTarget('@missing',null,agents));
});

test('suggestions exclude disabled and external personas', () => {
  assert.deepEqual(agentSuggestions('請 @doc',agents).map(a=>a.agent_key),['doc_writer']);
  assert.equal(agentSuggestions('no mention',agents).length,0);
});

test('historical messages retain the executed persona after profile rename', () => {
  const label=messagePersona({agent_key:'doc_writer',agent_snapshot:{display_name:'原始寫作代理',icon:'✍️'},model:'executed-model'});
  assert.match(label,/原始寫作代理/);
  assert.match(label,/executed-model/);
});
