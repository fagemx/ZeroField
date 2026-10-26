import { stable } from './writingModel.js';

const RECEIPT_WINDOW = 24 * 60 * 60 * 1000;
const copy = value => structuredClone(value);
const fail = (message, code = 'START_HANDOFF_INVALID') => Object.assign(new Error(message), {code});
const fingerprint = async value => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(stable(value)))))
  .map(byte => byte.toString(16).padStart(2, '0')).join('');

// Only plain, blank paragraphs count as empty. Images, tables, headings, template text and
// unfamiliar nodes are occupied content, even when a text-only extractor would say empty.
export function isEmptyStartDocument(doc) {
  return doc?.type === 'doc' && Array.isArray(doc.content) && doc.content.every(node =>
    node.type === 'paragraph' && (node.content || []).every(child => child.type === 'hardBreak' || child.type === 'text' && !child.text?.trim()));
}

function plainDocument(text, identifier) {
  const content = [];
  text.replace(/\r\n?/g, '\n').split('\n').forEach((line, index) => {
    if (index) content.push({type:'hardBreak'});
    if (line) content.push({type:'text', text:line});
  });
  // One block avoids the 200-op limit; literal text is never HTML/Markdown or a template guess.
  return {type:'doc', content:[{type:'paragraph', attrs:{bid:identifier, owner:null, created:null}, content}]};
}

function requireResource(value) {
  if (!value?.docHash || !value.doc || !Number.isInteger(value.version ?? value.revision)) throw fail('Writing resource has no authoritative fingerprint or version.');
  return value;
}

function checkSave(ack, request, doc) {
  if (ack?.clientMutationId !== request.body.clientMutationId || !ack.docHash || ack.conflicts?.length) {
    throw fail('The start text was not acknowledged without conflicts.', 'START_HANDOFF_CONFLICT');
  }
  const expected = doc.content[0], saved = ack.doc?.content?.find(node => node.attrs?.bid === expected.attrs.bid);
  if (!saved || saved.type !== expected.type || stable(saved.content) !== stable(expected.content)) {
    throw fail('The start acknowledgement does not contain the submitted text.', 'START_HANDOFF_CONFLICT');
  }
}

// transport MUST already be bound to the current actor and episode. The caller owns pending
// text and a stable idempotencyKey (normally start.handoffId), NEVER a new key on retry.
// onCheckpoint(plan) MUST durably store start.handoff with the pending start before resolving;
// throwing/returning false stops BEFORE a mutation. Reuse that checkpoint across reloads.
// Receipt replay additionally requires the SAME authentication credential, not merely the
// same actor ID: a logout/new login must not automatically replay an ambiguous branch POST.
// No React, local journal, model calls, resource loading or pending-start acknowledgement here.
export async function persistStartHandoff({transport, start, name = 'Story start', idempotencyKey, actorId, onCheckpoint}) {
  if (typeof transport !== 'function' || typeof onCheckpoint !== 'function' || !actorId || typeof idempotencyKey !== 'string' || !idempotencyKey || idempotencyKey.length > 128 ||
    !['idea','novel','script'].includes(start?.mode) || typeof start.text !== 'string' || !start.text.trim() || start.text.length > 500000) {
    throw fail('A valid start, actor, stable key, transport and durable checkpoint callback are required.');
  }
  const inputHash = await fingerprint({mode:start.mode, text:start.text, idempotencyKey});
  const token = await fingerprint(idempotencyKey), mutation = suffix => `start-${token.slice(0, 48)}-${suffix}`;
  const doc = plainDocument(start.text, 'b_start_' + token.slice(0, 32));
  let plan = start.handoff ? copy(start.handoff) : null;
  if (plan && (plan.schemaVersion !== 1 || plan.actorId !== actorId || plan.inputHash !== inputHash)) {
    throw fail('This pending start belongs to another actor or input.', 'START_HANDOFF_IDENTITY_MISMATCH');
  }
  const checkpoint = async next => {
    plan = copy(next);
    start.handoff = copy(plan);
    if (await onCheckpoint(copy(plan)) === false) throw fail('The pending start checkpoint could not be stored.', 'START_HANDOFF_CHECKPOINT_FAILED');
  };
  const request = (tail, method, body, suffix) => ({tail, method, body, idempotencyKey:mutation(suffix)});
  const done = async ref => {await checkpoint({...plan, stage:'done', ref, request:null});return copy(ref);};
  const branchPlan = (resource, sourceRef) => {
    requireResource(resource);
    return {...plan, stage:'branch-create', request:request('branches', 'POST', {
      sourceRef, name:String(name || 'Story start').trim().slice(0, 200) || 'Story start', expectedSourceHash:resource.docHash,
    }, 'branch-create')};
  };
  const sourcePlan = resource => ({...plan, stage:'source-save', request:request(`sources/${start.mode}`, 'PUT', {
    baseVersion:resource?.version || 0, clientMutationId:mutation('source-save'), doc,
    structure:resource?.structure || {}, composition:resource?.composition || {},
  }, 'source-save')});
  const workingPlan = () => ({...plan, stage:'working-save', request:request('script/ops', 'POST', {
    ops:[{op:'put', bid:doc.content[0].attrs.bid, after:null, node:doc.content[0], base:null}],
    atomic:true, clientMutationId:mutation('working-save'), session_id:mutation('session'),
  }, 'working-save')});

  // Bind even a read failure to its originating actor before doing any network work.
  if (!plan) await checkpoint({schemaVersion:1, actorId, inputHash, createdAt:Date.now(), stage:'select', request:null});
  if (plan.stage === 'select') {
    if (start.mode !== 'script') {
      const source = await transport(`sources/${start.mode}`);
      if (source) requireResource(source);
      await checkpoint(!source || isEmptyStartDocument(source.doc) ? sourcePlan(source) : branchPlan(source, {kind:'source', mode:start.mode}));
    } else {
      const working = requireResource(await transport('workspace'));
      if (!isEmptyStartDocument(working.doc)) await checkpoint(branchPlan(working, {kind:'working'}));
      else if (!working.structure?.initialized) await checkpoint({...plan, stage:'initialize', request:request('initialize', 'POST', {expectedDocHash:working.docHash}, 'initialize')});
      else await checkpoint(workingPlan());
    }
  }

  while (plan.stage !== 'done') {
    // Receipts are 24h and credential-scoped. An ambiguous expired operation is NOT a
    // licence to mint a new identity/create another branch. Keep pending text for recovery.
    if (!Number.isFinite(plan.createdAt) || Date.now() - plan.createdAt >= RECEIPT_WINDOW) {
      throw fail('This start retry receipt may have expired; keep the pending text for manual recovery.', 'START_HANDOFF_RETRY_EXPIRED');
    }
    const pending = plan.request;
    if (!pending?.tail || !pending.body || !pending.idempotencyKey) throw fail('The pending start checkpoint is incomplete.');
    // Re-persist even on replay: a failed checkpoint may have left only an in-memory plan.
    await checkpoint(plan);
    let ack;
    try {
      ack = await transport(pending.tail, pending.method, copy(pending.body), {idempotencyKey:pending.idempotencyKey});
    } catch (error) {
      // An empty source CAS can lose to another writer. Never rebase over their text.
      // Only an explicit ordinary CAS conflict permits switching to a new private branch;
      // idempotency conflicts, authorization loss and unknown transport failures stay pending.
      if (plan.stage !== 'source-save' || error.code !== 'DRAMA_WRITING_CONFLICT') throw error;
      const source = requireResource(await transport(`sources/${start.mode}`));
      await checkpoint(branchPlan(source, {kind:'source', mode:start.mode}));
      continue;
    }
    if (plan.stage === 'initialize') {
      // Initialization and saving are separate transactions: re-read before choosing working.
      const working = requireResource(await transport('workspace'));
      await checkpoint(isEmptyStartDocument(working.doc) ? workingPlan() : branchPlan(working, {kind:'working'}));
    } else if (plan.stage === 'branch-create') {
      if (!ack?.branchId || !Number.isInteger(ack.version) || !ack.docHash) throw fail('The private branch creation was not acknowledged.');
      await checkpoint({...plan, stage:'branch-save', ref:{kind:'branch', id:ack.branchId}, request:request(`branches/${encodeURIComponent(ack.branchId)}`, 'PUT', {
        baseVersion:ack.version, clientMutationId:mutation('branch-save'), doc,
        // No copied structure/composition: branch saves reconcile their protected metadata.
      }, 'branch-save')});
    } else if (['source-save','branch-save','working-save'].includes(plan.stage)) {
      checkSave(ack, pending, doc);
      return done(plan.stage === 'source-save' ? {kind:'source', mode:start.mode} : plan.stage === 'working-save' ? {kind:'working'} : plan.ref);
    } else throw fail('Unknown pending start stage.');
  }
  if (!plan.ref || !['working','source','branch'].includes(plan.ref.kind)) throw fail('The completed start has no resource reference.');
  return copy(plan.ref);
}
