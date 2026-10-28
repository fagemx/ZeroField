import test from 'node:test';
import assert from 'node:assert/strict';
import {persistStartHandoff, isEmptyStartDocument, startLayout, startDocument, startOverflow, START_OPS_LIMIT, START_BLOCK_LIMIT} from '../src/writing/writingStartHandoff.js';
import {createActorBoundRequest, createWritingTransport} from '../src/writing/writingTransport.js';
import {stable} from '../src/writing/writingModel.js';

const copy = value => structuredClone(value);
const paragraph = (text = '', bid = 'b_existing') => ({type:'paragraph', attrs:{bid,owner:null,created:null}, ...(text ? {content:[{type:'text',text}]} : {})});
const document = text => ({type:'doc',content:[paragraph(text)]});
const resource = (text = '', version = 1) => ({doc:document(text), docHash:`hash-${version}-${text}`, version, structure:{initialized:true}, composition:{}});
const conflict = () => Object.assign(new Error('CAS conflict'), {status:409,code:'DRAMA_WRITING_CONFLICT'});

// This is a deliberately in-process mock of the inspected writing API contracts, NOT an
// HTTP/server/PostgreSQL test. It validates exact request fields, CAS and receipt replay.
function mockWriting({working = resource(), sources = {}, initialized = true} = {}) {
  const state = {working:copy(working), sources:copy(sources), branches:{}, calls:[], receipts:new Map(), created:0, lose:null, before:null, badAck:null};
  state.working.structure.initialized = initialized;
  const transport = async (tail, method = 'GET', body, options = {}) => {
    state.calls.push({tail,method,body:copy(body),options:copy(options)});
    if (state.before) await state.before({tail,method,body,state});
    if (method === 'GET') {
      if (tail === 'workspace') return copy(state.working);
      if (tail.startsWith('sources/')) return copy(state.sources[tail.split('/')[1]] || null);
      if (tail.startsWith('branches/')) return copy(state.branches[tail.split('/')[1]]);
      throw new Error('Unexpected mock GET ' + tail);
    }
    const identity = method === 'POST' ? options.idempotencyKey : body.clientMutationId;
    assert.ok(identity && identity.length <= 128, 'stable mutation identity required by writing dispatch');
    const key = method + ':' + tail + ':' + identity, previous = state.receipts.get(key);
    if (previous) {
      if (previous.body !== stable(body)) throw Object.assign(new Error('Identity used with another body'), {status:409,code:'DRAMA_IDEMPOTENCY_CONFLICT'});
      return copy(previous.ack);
    }
    let ack;
    if (tail === 'initialize') {
      assert.deepEqual(Object.keys(body).sort(), ['expectedDocHash']);
      assert.equal(body.expectedDocHash, state.working.docHash);
      state.working.structure.initialized = true;
      ack = {initialized:true};
    } else if (tail.startsWith('sources/')) {
      assert.equal(method, 'PUT');
      assert.deepEqual(Object.keys(body).sort(), ['baseVersion','clientMutationId','composition','doc','structure']);
      const mode = tail.split('/')[1], current = state.sources[mode];
      if ((current?.version || 0) !== body.baseVersion) throw conflict();
      ack = {...copy(body), version:body.baseVersion+1, docHash:'saved-source-'+identity};
      state.sources[mode] = copy(ack);
    } else if (tail === 'branches') {
      assert.equal(method, 'POST');
      assert.deepEqual(Object.keys(body).sort(), ['expectedSourceHash','name','sourceRef']);
      const source = body.sourceRef.kind === 'working' ? state.working : state.sources[body.sourceRef.mode];
      if (source.docHash !== body.expectedSourceHash) throw conflict();
      const branchId = 'wbr_mock'+(++state.created);
      ack = {...copy(source), version:1, branchId, name:body.name};
      state.branches[branchId] = copy(ack);
    } else if (tail.startsWith('branches/')) {
      assert.equal(method, 'PUT');
      assert.deepEqual(Object.keys(body).sort(), ['baseVersion','clientMutationId','doc']);
      const id = tail.split('/')[1], current = state.branches[id];
      if (body.baseVersion !== current.version) throw conflict();
      ack = {...current,doc:copy(body.doc),version:current.version+1,docHash:'saved-branch-'+identity,clientMutationId:body.clientMutationId};
      state.branches[id] = copy(ack);
    } else if (tail === 'script/ops') {
      assert.equal(method, 'POST');
      assert.deepEqual(Object.keys(body).sort(), ['atomic','clientMutationId','ops','session_id']);
      assert.equal(body.atomic, true);
      assert.ok(body.session_id.length <= 64);
      assert.ok(body.ops.length >= 1 && body.ops.length <= 200, 'one request within the server MAX_OPS');
      // Only atomic inserts, never deletes or reorder: the first at the top, each next one after the previous bid.
      body.ops.forEach((op, index) => {
        assert.equal(op.op, 'put');assert.equal(op.base, null);
        assert.equal(op.after, index ? body.ops[index - 1].bid : null);
        assert.match(op.bid, /^[A-Za-z0-9_-]{4,40}$/);assert.equal(op.node.attrs.bid, op.bid);
      });
      assert.equal(new Set(body.ops.map(op => op.bid)).size, body.ops.length);
      assert.equal(state.working.structure.initialized, true);
      const collisions = body.ops.filter(op => state.working.doc.content.some(node => node.attrs?.bid === op.bid));
      const doc = collisions.length ? state.working.doc : {...state.working.doc,content:[...body.ops.map(op => copy(op.node)),...state.working.doc.content]};
      ack = {doc:copy(doc),docHash:'saved-script-'+identity,version:state.working.version+1,clientMutationId:body.clientMutationId,conflicts:collisions.map(op => ({bid:op.bid}))};
      if (!collisions.length) state.working = {...state.working,...copy(ack)};
    } else throw new Error('Unexpected mock mutation ' + tail);
    if (state.badAck) ack = state.badAck(copy(ack));
    state.receipts.set(key, {body:stable(body),ack:copy(ack)});
    if (state.lose === tail) {state.lose = null;throw new Error('Simulated lost response after mock commit');}
    return copy(ack);
  };
  return {state,transport};
}

function caller(mock, mode = 'idea', text = 'A signal.\n\n<script>literal</script> & rain.') {
  let saved;
  const start = {mode,text,handoffId:'stable-start-key'};
  const args = {transport:mock.transport,start,actorId:'actor-a',idempotencyKey:start.handoffId,name:'Imported start',onCheckpoint:async plan => {saved = JSON.stringify({...start,handoff:plan});}};
  return {args, start, reload:() => ({...args,start:JSON.parse(saved)}), saved:() => JSON.parse(saved)};
}
const mutations = mock => mock.state.calls.filter(call => call.method !== 'GET');

test('only plain blank paragraphs count as empty; template text, images and unfamiliar structure never do', () => {
  for (const doc of [{type:'doc',content:[]}, document(''), document('  \n ')]) assert.equal(isEmptyStartDocument(doc), true);
  for (const doc of [null, {}, document('Template screenplay'), {type:'doc',content:[{type:'heading'}]}, {type:'doc',content:[{type:'image'}]}, {type:'doc',content:[{type:'paragraph',content:[{type:'fill'}]}]}, {type:'doc',content:[{type:'table'}]}]) assert.equal(isEmptyStartDocument(doc), false);
});

test('idea and novel save missing or empty private sources with authoritative CAS and literal text', async () => {
  for (const mode of ['idea','novel']) for (const existing of [null,resource('')]) {
    const mock = mockWriting({sources:existing ? {[mode]:existing} : {}}), c = caller(mock, mode);
    const ref = await persistStartHandoff(c.args);
    assert.deepEqual(ref, {kind:'source',mode});
    const put = mutations(mock)[0];
    assert.equal(put.body.baseVersion, existing?.version || 0);
    assert.equal(mock.state.created, 0);
    assert.deepEqual(put.body.doc.content.map(block => block.content.map(node => node.text)), [['A signal.'], ['<script>literal</script> & rain.']]);
    assert.equal(c.saved().handoff.stage, 'done');
    const count = mock.state.calls.length;
    assert.deepEqual(await persistStartHandoff(c.reload()), ref, 'saved but load/host ACK failed: reuse the completed resource');
    assert.equal(mock.state.calls.length, count, 'completed reload does not touch the server');
  }
});

test('occupied sources and every nonempty screenplay (including template-like prose) are preserved in private branches', async () => {
  for (const mode of ['idea','novel','script']) {
    const original = resource(mode === 'script' ? '# Screenplay\nLens: cinema × suspense' : 'Keep my existing source.', 7);
    const mock = mockWriting({working:original,sources:{[mode]:original}}), c = caller(mock,mode);
    assert.deepEqual(await persistStartHandoff(c.args), {kind:'branch',id:'wbr_mock1'});
    assert.equal(mock.state.created, 1);
    assert.deepEqual(mode === 'script' ? mock.state.working : mock.state.sources[mode], original);
    const [create,save] = mutations(mock);
    assert.equal(create.tail, 'branches');assert.equal(create.body.expectedSourceHash, original.docHash);
    assert.deepEqual(create.body.sourceRef, mode === 'script' ? {kind:'working'} : {kind:'source',mode});
    assert.equal(save.tail, 'branches/wbr_mock1');assert.equal(save.body.baseVersion, 1);
    assert.equal(c.saved().handoff.ref.id, 'wbr_mock1');
  }
});

test('empty working script is initialized when needed and saved only with a deterministic atomic insertion', async () => {
  const mock = mockWriting({initialized:false}), c = caller(mock,'script','INT. DOME\r\nKael enters.\r\nHe stops.');
  assert.deepEqual(await persistStartHandoff(c.args), {kind:'working'});
  assert.deepEqual(mutations(mock).map(call => call.tail), ['initialize','script/ops']);
  const ops = mutations(mock)[1].body.ops;
  assert.deepEqual(ops.map(op => op.node.content), [[{type:'text',text:'INT. DOME'}],
    [{type:'text',text:'Kael enters.'},{type:'hardBreak'},{type:'text',text:'He stops.'}]]);
  assert.equal(mock.state.created, 0);
});

test('a script becoming occupied during initialize is preserved and the start goes to a private branch', async () => {
  const mock = mockWriting({initialized:false}), c = caller(mock,'script');
  mock.state.before = ({tail,method,state}) => {
    if (tail === 'workspace' && method === 'GET' && state.working.structure.initialized) state.working = resource('Another writer arrived.',2);
  };
  assert.deepEqual(await persistStartHandoff(c.args), {kind:'branch',id:'wbr_mock1'});
  assert.equal(mock.state.working.doc.content[0].content[0].text, 'Another writer arrived.');
  assert.ok(!mutations(mock).some(call => call.tail === 'script/ops'));
});

test('GET-to-save insertion race cannot overwrite/delete/reorder other working blocks (not whole-document CAS)', async () => {
  const mock = mockWriting(), c = caller(mock,'script');
  mock.state.before = ({tail,state}) => {if (tail === 'script/ops') state.working = resource('Concurrent block.',2);};
  assert.deepEqual(await persistStartHandoff(c.args), {kind:'working'});
  assert.deepEqual(mock.state.working.doc.content.map(block => block.content[0].text), ['A signal.','<script>literal</script> & rain.','Concurrent block.']);
});

test('empty source losing its version CAS moves to a private branch instead of rebasing over the winner', async () => {
  const mock = mockWriting({sources:{idea:resource('')}}), c = caller(mock);
  mock.state.before = ({tail,method,state}) => {
    if (tail === 'sources/idea' && method === 'PUT') {state.before = null;state.sources.idea = resource('The winner stays.',2);}
  };
  assert.deepEqual(await persistStartHandoff(c.args), {kind:'branch',id:'wbr_mock1'});
  assert.equal(mock.state.sources.idea.doc.content[0].content[0].text, 'The winner stays.');
});

for (const stage of ['sources/idea','initialize','script/ops','branches','branches/wbr_mock1']) {
  test(`lost mock ACK at ${stage} replays the exact saved body/key across reload, without extra branch or overwritten source`, async () => {
    const mode = stage === 'sources/idea' ? 'idea' : 'script';
    const mock = mockWriting({working:resource(stage.startsWith('branches') ? 'Existing screenplay.' : ''),initialized:stage !== 'initialize'}), c = caller(mock,mode);
    mock.state.lose = stage;
    await assert.rejects(persistStartHandoff(c.args), /lost response/);
    assert.notEqual(c.saved().handoff.stage, 'done');
    const before = mutations(mock).filter(call => call.tail === stage)[0];
    const ref = await persistStartHandoff(c.reload());
    const replays = mutations(mock).filter(call => call.tail === stage);
    assert.deepEqual(replays[1], before, 'same method, body and idempotency identity');
    assert.equal(mock.state.created, stage.startsWith('branches') ? 1 : 0);
    assert.equal(ref.kind, stage.startsWith('branches') ? 'branch' : stage === 'sources/idea' ? 'source' : 'working');
  });
}

test('failure persisting branchId after a mock commit replays create before continuing, not a new POST identity', async () => {
  const mock = mockWriting({working:resource('Existing script.')}), c = caller(mock,'script');
  const save = c.args.onCheckpoint;
  c.args.onCheckpoint = async plan => {if (plan.stage === 'branch-save') throw new Error('Storage full after create');await save(plan);};
  await assert.rejects(persistStartHandoff(c.args), /Storage full/);
  assert.equal(c.saved().handoff.stage, 'branch-create');
  const retry = c.reload();retry.onCheckpoint = save;
  assert.deepEqual(await persistStartHandoff(retry), {kind:'branch',id:'wbr_mock1'});
  assert.equal(mock.state.created, 1);
});

test('no server mutation is allowed before a durable checkpoint; read failure still binds pending to actor', async () => {
  const mock = mockWriting(), c = caller(mock);
  await assert.rejects(persistStartHandoff({...c.args,onCheckpoint:async () => false}), {code:'START_HANDOFF_CHECKPOINT_FAILED'});
  assert.equal(mock.state.calls.length, 0);
  const broken = caller(mock);
  await assert.rejects(persistStartHandoff({...broken.args,transport:async () => {throw new Error('Offline');}}), /Offline/);
  assert.equal(broken.saved().handoff.actorId, 'actor-a');
  await assert.rejects(persistStartHandoff({...broken.reload(),actorId:'actor-b'}), {code:'START_HANDOFF_IDENTITY_MISMATCH'});
});

test('changed input/actor, expired mutation, idempotency conflict and script save conflicts never complete or retry with a new key', async () => {
  for (const badAck of [ack => ({...ack,conflicts:[{bid:'locked'}]}), ack => ({...ack,clientMutationId:'wrong'}), ack => ({...ack,docHash:null}), ack => ({...ack,doc:document('Wrong content')}),
    // Every submitted block is checked, not only the first: a missing, changed or reordered later block is a conflict.
    ack => ({...ack,doc:{...ack.doc,content:ack.doc.content.filter((_, index) => index !== 1)}}),
    ack => ({...ack,doc:{...ack.doc,content:ack.doc.content.map((node, index) => index === 1 ? {...node,content:[{type:'text',text:'Changed.'}]} : node)}}),
    ack => ({...ack,doc:{...ack.doc,content:[ack.doc.content[1],ack.doc.content[0],...ack.doc.content.slice(2)]}})]) {
    const mock = mockWriting(), c = caller(mock,'script');mock.state.badAck = badAck;
    await assert.rejects(persistStartHandoff(c.args), {code:'START_HANDOFF_CONFLICT'});
    assert.equal(c.saved().handoff.stage, 'working-save');
  }
  const mock = mockWriting({working:resource('Keep existing.')}), c = caller(mock,'script');mock.state.lose = 'branches';
  await assert.rejects(persistStartHandoff(c.args));
  const changed = c.reload();changed.start.text = 'Changed input';
  await assert.rejects(persistStartHandoff(changed), {code:'START_HANDOFF_IDENTITY_MISMATCH'});
  const expired = c.reload();expired.start.handoff.createdAt -= 24*60*60*1000;
  const count = mutations(mock).length;
  await assert.rejects(persistStartHandoff(expired), {code:'START_HANDOFF_RETRY_EXPIRED'});
  assert.equal(mutations(mock).length, count);
  const conflictRetry = c.reload();
  conflictRetry.transport = async () => {throw Object.assign(new Error('Wrong idempotency body'), {status:409,code:'DRAMA_IDEMPOTENCY_CONFLICT'});};
  await assert.rejects(persistStartHandoff(conflictRetry), {code:'DRAMA_IDEMPOTENCY_CONFLICT'});
  assert.equal(mock.state.created, 1);
});

test('branch CAS refuses concurrent private edits after creation instead of overwriting or creating a second branch', async () => {
  const mock = mockWriting({working:resource('Existing.')}), c = caller(mock,'script');
  mock.state.before = ({tail,state}) => {if (tail === 'branches/wbr_mock1') state.branches.wbr_mock1.version = 2;};
  await assert.rejects(persistStartHandoff(c.args), {code:'DRAMA_WRITING_CONFLICT'});
  assert.equal(mock.state.created, 1);
  assert.equal(c.saved().handoff.stage, 'branch-save');
});

test('helper uses the supplied actor-bound writing transport, including disposal and expected-actor propagation', async () => {
  const mock = mockWriting();
  const bound = createActorBoundRequest('actor-a', async (path,method,body,options) => {
    assert.equal(options.expectedActorId, 'actor-a');
    assert.ok(path.startsWith('/episodes/ep_example_01/writing/'));
    const {signal,expectedActorId,...rest} = options;
    return mock.transport(path.split('/writing/')[1],method,body,rest);
  });
  const c = caller(mock);c.args.transport = createWritingTransport('ep_example_01',bound);
  assert.deepEqual(await persistStartHandoff(c.args), {kind:'source',mode:'idea'});
  bound.dispose();
  const other = caller(mock,'novel');other.args.transport = c.args.transport;
  await assert.rejects(persistStartHandoff(other.args), {name:'AbortError'});
  assert.equal(other.saved().handoff.stage, 'select');
});

// R44-3: a pasted screenplay becomes scene-shaped blocks, not one paragraph.
const SPILLWAY = 'SPILLWAY\r\nan original short\r\n\r\n1. INT. CONTROL ROOM - NIGHT\r\nRain hammers the glass.\r\nNora faces the gauges.\r\n\r\nNORA\r\n"The gate is jammed."\r\n\r\n2. EXT. DAM CREST - CONTINUOUS\r\nEli grips the rail.\r\n\r\n\r\n3. EXT. SPILLWAY - NIGHT\r\nEli runs toward us.\r\n';
const lines = block => block.content.map(node => node.type === 'hardBreak' ? '\n' : node.text).join('');
const scriptOf = count => 'TITLE PAGE\n\n' + Array.from({length:count}, (_, i) => `${i + 1}. INT. ROOM ${i + 1} - DAY\nOne of ${i + 1}.\nTwo of ${i + 1}.\n\nThree of ${i + 1}.`).join('\n\n');
// Text kept exactly, except that a blank line and a block boundary are the same thing.
const flat = value => value.replace(/\r\n?/g, '\n').trim().replace(/\n\n+/g, '\n');
const textOf = doc => doc.content.map(lines).join('\n');

test('a numbered screenplay saves each heading line as its own block in one atomic, chained request', async () => {
  const mock = mockWriting(), c = caller(mock, 'script', SPILLWAY);
  assert.deepEqual(await persistStartHandoff(c.args), {kind:'working'});
  const [save] = mutations(mock);
  assert.equal(save.tail, 'script/ops');
  assert.deepEqual(save.body.ops.map(op => lines(op.node)), ['SPILLWAY\nan original short', '1. INT. CONTROL ROOM - NIGHT',
    'Rain hammers the glass.\nNora faces the gauges.', 'NORA\n"The gate is jammed."', '2. EXT. DAM CREST - CONTINUOUS',
    'Eli grips the rail.', '3. EXT. SPILLWAY - NIGHT', 'Eli runs toward us.']);
  assert.ok(save.body.ops.every(op => op.node.type === 'paragraph' && op.node.content.every(node => node.type !== 'text' || node.text)));
  assert.deepEqual(mock.state.working.doc.content.slice(0, 8).map(node => node.attrs.bid), save.body.ops.map(op => op.bid));
});

test('the same start text and key always give the same blocks and ids, whichever save receives them', async () => {
  const runs = [];
  for (let i = 0; i < 2; i++) {
    const mock = mockWriting(), c = caller(mock, 'script', SPILLWAY);
    await persistStartHandoff(c.args);
    runs.push(mutations(mock)[0].body);
  }
  assert.deepEqual(runs[0], runs[1]);
  const token = 'c'.repeat(64);
  assert.deepEqual(startDocument(SPILLWAY, token, START_BLOCK_LIMIT), startDocument(SPILLWAY, token, START_BLOCK_LIMIT));
  // A small script is laid out the same for script/ops (200) and a whole-document PUT (1,000).
  assert.deepEqual(startDocument(SPILLWAY, token, START_OPS_LIMIT), startDocument(SPILLWAY, token, START_BLOCK_LIMIT));
  const source = mockWriting(), s = caller(source, 'novel', SPILLWAY);
  await persistStartHandoff(s.args);
  assert.deepEqual(mutations(source)[0].body.doc.content.map(lines), runs[0].ops.map(op => lines(op.node)));
});

test('over the op limit, body paragraphs merge within their scene first and every heading keeps its block', () => {
  // 60 scenes x (heading + 2 paragraphs) + title page = 181 blocks: under 200, block for block.
  assert.equal(startLayout(scriptOf(60), START_OPS_LIMIT).mode, 'blocks');
  // 80 scenes need 241: paragraphs merge (a blank line becomes two hard breaks), headings stay alone.
  const merged = startLayout(scriptOf(80), START_OPS_LIMIT);
  assert.deepEqual([merged.mode, merged.blocks.length, merged.scenes, merged.separateScenes], ['paragraphs', 200, 80, 80]);
  const doc = startDocument(scriptOf(80), 'd'.repeat(64), START_OPS_LIMIT);
  assert.equal(doc.content.filter(block => /^\d+\. INT\. /.test(lines(block)) && !lines(block).includes('\n')).length, 80);
  assert.ok(doc.content.some(block => lines(block).includes('Two of 80.\n\nThree of 80.')));
  assert.equal(flat(textOf(doc)), flat(scriptOf(80)));
});

test('150 scenes fit one 200-op save; past the limit no text is dropped and the overflow is reported', () => {
  const doc = startDocument(scriptOf(150), 'e'.repeat(64), START_OPS_LIMIT);
  assert.equal(doc.content.length, 200);
  // Later scenes carry their body in the heading block after one hard break; the heading line still starts it.
  const starts = doc.content.map(block => lines(block).split('\n')[0]).filter(line => /^\d+\. INT\. /.test(line));
  assert.deepEqual(starts, Array.from({length:150}, (_, i) => `${i + 1}. INT. ROOM ${i + 1} - DAY`));
  assert.equal(lines(doc.content.at(-1)), '150. INT. ROOM 150 - DAY\nOne of 150.\nTwo of 150.\n\nThree of 150.');
  assert.equal(flat(textOf(doc)), flat(scriptOf(150)));
  assert.equal(startOverflow(scriptOf(150), {kind:'working'}), null);
  // A branch or source PUT holds 1,000 blocks: 150 scenes keep every paragraph.
  assert.equal(startLayout(scriptOf(150), START_BLOCK_LIMIT).mode, 'blocks');
  // 250 scenes cannot all start a block in 200 ops: the rest share the last block, all text kept.
  const over = startDocument(scriptOf(250), 'f'.repeat(64), START_OPS_LIMIT);
  assert.equal(over.content.length, 200);
  assert.equal(flat(textOf(over)), flat(scriptOf(250)));
  assert.deepEqual(startOverflow(scriptOf(250), {kind:'working'}), {scenes:250, separateScenes:199});
  assert.equal(startOverflow(scriptOf(250), {kind:'branch', id:'wbr_x'}), null);
});
