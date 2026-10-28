import { stable } from './writingModel.js';
import { isSceneHeading } from './sceneHeading.js';

// Server limits one start save must fit:
// - POST script/ops takes at most 200 ops per request (project_docs/blocks.py MAX_OPS), and the start is ONE atomic request;
// - PUT sources/{mode} and branches/{id} replace the whole document: at most 1,000 structure units
//   (writing_structure.reconcile_structure LIMIT_EXCEEDED) within the 2 MB / 500,000-character document limits.
export const START_OPS_LIMIT = 200;
export const START_BLOCK_LIMIT = 1000;
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

// Literal start text as blocks: never HTML/Markdown parsing, never a template guess. Each scene-heading line is
// its own paragraph (scenes are split per block); body text splits into paragraphs at blank (or whitespace-only)
// lines and keeps its other line breaks as hard breaks. A block is a list of segments (lines): one hard break
// between lines, two (a blank line) between segments. Over `limit` blocks no text is ever dropped; the layout
// degrades in this order:
//   1. body paragraphs merge within their own scene;
//   2. later scenes' bodies join their heading block after one hard break. The heading line still starts the
//      block, so the scene is still found and still titled by that line;
//   3. scenes past the limit join the last block after a blank line. They stay as text and can be split in the
//      editor; `separateScenes < scenes` reports it. With 200 ops this starts past 200 scenes (199 after a title page).
export function startLayout(text, limit) {
  const groups = [];
  let group = null, paragraph = null;
  for (const line of String(text).replace(/\r\n?/g, '\n').split('\n')) {
    if (isSceneHeading(line)) {groups.push(group = {heading:line, paragraphs:[]});paragraph = null;}
    else if (!line.trim()) paragraph = null;
    else {
      if (!group) groups.push(group = {heading:null, paragraphs:[]});
      if (!paragraph) group.paragraphs.push(paragraph = []);
      paragraph.push(line);
    }
  }
  const scenes = groups.filter(item => item.heading !== null).length;
  const headingBlock = item => item.heading === null ? [] : [[[item.heading]]];
  // n blocks of consecutive paragraphs, as even as possible and always in order.
  const chunks = (paragraphs, n) => Array.from({length:n}, (_, j) => paragraphs.slice(Math.floor(j * paragraphs.length / n), Math.floor((j + 1) * paragraphs.length / n)));
  const folded = item => item.heading === null ? [item.paragraphs] : [[[item.heading, ...(item.paragraphs[0] || [])], ...item.paragraphs.slice(1)]];
  let blocks, mode;
  if (groups.reduce((total, item) => total + (item.heading !== null) + item.paragraphs.length, 0) <= limit) {
    mode = 'blocks';
    blocks = groups.flatMap(item => [...headingBlock(item), ...item.paragraphs.map(lines => [lines])]);
  } else if (scenes + groups.filter(item => item.paragraphs.length).length <= limit) {
    // Water-fill: the largest even cap per scene that fits, the spare blocks to the first larger scenes.
    mode = 'paragraphs';
    const sizes = groups.map(item => item.paragraphs.length), available = limit - scenes;
    const used = cap => sizes.reduce((total, size) => total + Math.min(size, cap), 0);
    let low = 1, high = sizes.reduce((most, size) => Math.max(most, size), 1);
    while (low < high) {const middle = Math.ceil((low + high) / 2);if (used(middle) <= available) low = middle;else high = middle - 1;}
    let spare = available - used(low);
    blocks = groups.flatMap((item, index) => {
      const extra = sizes[index] > low && spare > 0 ? (spare--, 1) : 0;
      return [...headingBlock(item), ...chunks(item.paragraphs, Math.min(sizes[index], low) + extra)];
    });
  } else {
    mode = groups.length <= limit ? 'headings' : 'scenes';
    let split = Math.max(0, limit - groups.length);
    blocks = groups.flatMap(item => item.heading !== null && item.paragraphs.length && split > 0 ? (split--, [...headingBlock(item), item.paragraphs]) : folded(item));
    if (blocks.length > limit) blocks = [...blocks.slice(0, limit - 1), blocks.slice(limit - 1).flat()];
  }
  const separateScenes = blocks.filter(segments => isSceneHeading(segments[0][0])).length;
  return {blocks, scenes, separateScenes, mode};
}

function paragraphNode(segments, bid) {
  const content = [];
  segments.forEach((lines, index) => {
    if (index) content.push({type:'hardBreak'}, {type:'hardBreak'});
    lines.forEach((line, at) => {if (at) content.push({type:'hardBreak'});content.push({type:'text', text:line});});
  });
  return {type:'paragraph', attrs:{bid, owner:null, created:null}, content};
}

// The same text, token and limit always give the same document (the handoff is idempotent and checkpointed).
export function startDocument(text, token, limit) {
  const {blocks} = startLayout(text, limit);
  return {type:'doc', content:blocks.map((segments, index) => paragraphNode(segments, `bs_${token.slice(0, 24)}_${index}`))};
}

// The working screenplay is saved through script/ops, a source or branch as one document.
export const startLimit = ref => ref?.kind === 'working' ? START_OPS_LIMIT : START_BLOCK_LIMIT;

// Scenes that could not keep a block of their own at the saved destination (layout step 3), or null.
export function startOverflow(text, ref) {
  const {scenes, separateScenes} = startLayout(text, startLimit(ref));
  return separateScenes < scenes ? {scenes, separateScenes} : null;
}

function requireResource(value) {
  if (!value?.docHash || !value.doc || !Number.isInteger(value.version ?? value.revision)) throw fail('Writing resource has no authoritative fingerprint or version.');
  return value;
}

// Every block the request submitted (a whole document, or the nodes of its put ops) must come back with the same
// type and content, in the submitted order. Checked against the checkpointed request body, so a replay of an
// older single-block checkpoint is verified against what it actually sent.
function checkSave(ack, request) {
  if (ack?.clientMutationId !== request.body.clientMutationId || !ack.docHash || ack.conflicts?.length) {
    throw fail('The start text was not acknowledged without conflicts.', 'START_HANDOFF_CONFLICT');
  }
  const submitted = Array.isArray(request.body.ops) ? request.body.ops.map(op => ({bid:op.bid, node:op.node}))
    : (request.body.doc?.content || []).map(node => ({bid:node.attrs?.bid, node}));
  const saved = Array.isArray(ack.doc?.content) ? ack.doc.content : [];
  const position = new Map(saved.map((node, index) => [node?.attrs?.bid, index]));
  let previous = -1;
  for (const {bid, node} of submitted) {
    const index = position.get(bid), found = saved[index];
    if (!bid || !found || index <= previous || found.type !== node.type || stable(found.content) !== stable(node.content)) {
      throw fail('The start acknowledgement does not contain the submitted text.', 'START_HANDOFF_CONFLICT');
    }
    previous = index;
  }
  if (!submitted.length) throw fail('The start acknowledgement does not contain the submitted text.', 'START_HANDOFF_CONFLICT');
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
  const doc = startDocument(start.text, token, START_BLOCK_LIMIT);
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
  // All blocks in ONE atomic request, each inserted after the previous one, so they land together and in order.
  const workingPlan = () => {
    const nodes = startDocument(start.text, token, START_OPS_LIMIT).content;
    return {...plan, stage:'working-save', request:request('script/ops', 'POST', {
      ops:nodes.map((node, index) => ({op:'put', bid:node.attrs.bid, after:index ? nodes[index - 1].attrs.bid : null, node, base:null})),
      atomic:true, clientMutationId:mutation('working-save'), session_id:mutation('session'),
    }, 'working-save')};
  };

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
      checkSave(ack, pending);
      return done(plan.stage === 'source-save' ? {kind:'source', mode:start.mode} : plan.stage === 'working-save' ? {kind:'working'} : plan.ref);
    } else throw fail('Unknown pending start stage.');
  }
  if (!plan.ref || !['working','source','branch'].includes(plan.ref.kind)) throw fail('The completed start has no resource reference.');
  return copy(plan.ref);
}
