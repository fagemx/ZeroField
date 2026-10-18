import test from 'node:test';
import assert from 'node:assert/strict';
import { groupBoardItems, reconcileBoard, raceSelectionPayload, assignmentRequest, proposalChanges, cancellationRequest } from '../src/assistant/orchestrationModel.js';

test('a pending gate cancels its whole run and a working dispatch keeps exact admission', () => {
  assert.deepEqual(cancellationRequest('/base','project',{kind:'race_select',gate_id:'g',run_id:'r'}),
    {path:'/base/runs/r/cancel',body:{reason:'Batch canceled from Agent Board'}});
  assert.deepEqual(cancellationRequest('/base','project',{kind:'dispatch',dispatch_id:'d',admission_no:7}),
    {path:'/base/dispatches/d/cancel',body:{admission_no:7,reason:'Canceled from Agent Board'}});
});

test('deduplicate gate and proposal', () => {
  const grouped=groupBoardItems([{id:'gate:g',gate_id:'g',kind:'proposal_review',status:'awaiting_gate',proposal_ids:[8]},
    {id:'proposal:8',kind:'proposal_review',status:'awaiting_gate',proposal_ids:[8]},
    {id:'dispatch:d',kind:'dispatch',status:'running'},{id:'agent:a',kind:'agent',status:'busy'}]);
  assert.equal(grouped.needs_you.length,1);
  assert.equal(grouped.working.length,1);
  assert.equal(grouped.idle.length,1);
});

test('poll retains selected candidate and draft answer', () => {
  const previous={ui:{selected:{gate_id:'g',id:'gate:g'},drafts:{g:'1'},selectedProposalId:42}};
  const next=reconcileBoard(previous,{needs_you:[{gate_id:'g',id:'gate:g',kind:'race_select',status:'awaiting_gate'}],working:[],done:[],idle:[]});
  assert.equal(next.ui.selected.gate_id,'g');
  assert.equal(next.ui.selectedProposalId,42);
  assert.equal(next.ui.drafts.g,'1');
});

test('resolved remote gate keeps readable comparison but disables stale action', () => {
  const next=reconcileBoard({ui:{selected:{gate_id:'g',title:'Old comparison'},drafts:{g:'0'}}},
    {needs_you:[],working:[],done:[],idle:[]});
  assert.equal(next.ui.selected.stale,true);
  assert.equal(next.ui.selected.title,'Old comparison');
});

test('race payload uses proposal id not visible index', () => {
  assert.deepEqual(raceSelectionPayload({id:'g'},402,'choose-1'),
    {client_request_id:'choose-1',resolution:{proposal_id:402}});
  assert.throws(()=>raceSelectionPayload({id:'g'},0,'bad'));
});

test('selected hidden rows retain frozen assignment scope', () => {
  const scope={target_tab:'shots',table_id:'t',base_revision:3,row_ids:['r1','r3'],column_ids:['prompt','image']};
  const request=assignmentRequest({objective:'Fill',strategy:'fanout_rows',agentKey:'sheet_ops',scope,requestId:'request-1'});
  scope.row_ids.splice(0,2,'r2');
  assert.deepEqual(request.scope.row_ids,['r1','r3']);
  assert.equal(request.client_request_id,'request-1');
});

test('late response from previous project is ignored', () => {
  const current={needs_you:[],ui:{drafts:{}}};
  assert.equal(reconcileBoard(current,{needs_you:[{id:'private'}]},{responseSlug:'old',currentSlug:'new'}),current);
});

test('proposal differences preserve before and after text', () => {
  const changes=proposalChanges({action:'table_edit',target:{review:{groups:[{label:'第 1 列',changes:[{column:'說明',before:'Old',after:'New'}]}]}}});
  assert.equal(changes[0].changes[0].before,'Old');
  assert.equal(changes[0].changes[0].after,'New');
});
