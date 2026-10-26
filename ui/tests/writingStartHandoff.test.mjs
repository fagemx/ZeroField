import test from 'node:test';
import assert from 'node:assert/strict';
import {persistStartHandoff, isEmptyStartDocument} from '../src/writing/writingStartHandoff.js';
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
      assert.equal(body.ops.length, 1, 'only an atomic insert, never deletes or reorder');
      const op = body.ops[0];
      assert.equal(op.op, 'put');assert.equal(op.base, null);assert.equal(op.after, null);
      assert.equal(state.working.structure.initialized, true);
      const collision = state.working.doc.content.some(node => node.attrs?.bid === op.bid);
      const doc = collision ? state.working.doc : {...state.working.doc,content:[copy(op.node),...state.working.doc.content]};
      ack = {doc:copy(doc),docHash:'saved-script-'+identity,version:state.working.version+1,clientMutationId:body.clientMutationId,conflicts:collision ? [{bid:op.bid}] : []};
      if (!collision) state.working = {...state.working,...copy(ack)};
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
    assert.equal(put.body.doc.content[0].content.find(node => node.text?.includes('<script>')).text, '<script>literal</script> & rain.');
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
  const mock = mockWriting({initialized:false}), c = caller(mock,'script','INT. DOME\r\nKael enters.');
  assert.deepEqual(await persistStartHandoff(c.args), {kind:'working'});
  assert.deepEqual(mutations(mock).map(call => call.tail), ['initialize','script/ops']);
  const op = mutations(mock)[1].body.ops[0];
  assert.match(op.bid, /^[A-Za-z0-9_-]{4,40}$/);
  assert.equal(op.node.content[1].type, 'hardBreak');
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
  assert.equal(mock.state.working.doc.content[1].content[0].text, 'Concurrent block.');
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
  for (const badAck of [ack => ({...ack,conflicts:[{bid:'locked'}]}), ack => ({...ack,clientMutationId:'wrong'}), ack => ({...ack,docHash:null}), ack => ({...ack,doc:document('Wrong content')})]) {
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
