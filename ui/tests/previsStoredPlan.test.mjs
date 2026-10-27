import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {DOME, defaultPlan, describePlan, planFromSlate} from '../src/previs/plan.js';
import {PLAN_CONFLICT, addCastMember, codesOnSet, loadPlan, plansToLoad, readDraft, removeCastMember, samePlan, savePlan, setCastCode, slateFromPlan, storable, storedPlan} from '../src/previs/storyPlan.js';

// SPEC_20 R26/R29: the stage stores a story shot's plan in the project by revision, settles a lost update, and writes the
// slate text a plan reads as. The fake server below keeps the route's contract: PUT names the revision with If-Match, a stale
// one is refused with DRAMA_PREVIS_REVISION_CONFLICT, the same plan again is not a new revision.
function fakeServer() {
  const shots = new Map(), calls = [];
  const castOptions = [{code: '@CAST-01', name: 'Kael'}, {code: '@CAST-02', name: 'Mira'}];
  const state = id => shots.get(id) || {plan: null, planRevision: 0, updatedAt: null, updatedBy: null};
  const request = async (path, method = 'GET', body, options = {}) => {
    calls.push({path, method, body, headers: options.headers || {}});
    const id = path.match(/^\/shots\/([^/]+)\/previs-plan$/)?.[1];
    if (!id) throw Object.assign(new Error('Story API endpoint not found.'), {status: 404, code: 'DRAMA_NOT_FOUND'});
    const now = state(id);
    if (method === 'PUT') {
      const base = Number(/^"(\d+)"$/.exec(options.headers?.['If-Match'] || '')?.[1]);
      if (base !== now.planRevision) {
        throw Object.assign(new Error('changed'), {status: 409, code: PLAN_CONFLICT, details: {currentRevision: now.planRevision, baseRevision: base}});
      }
      if (JSON.stringify(body.plan) !== JSON.stringify(now.plan)) {
        shots.set(id, {plan: JSON.parse(JSON.stringify(body.plan)), planRevision: now.planRevision + 1, updatedAt: 't' + (now.planRevision + 1), updatedBy: 'me'});
      }
    }
    return {shotId: id, ...state(id), castOptions};
  };
  return {request, calls, shots};
}

test('saving names the revision it started from, and a lost update comes back as a conflict holding the stored plan', async () => {
  const server = fakeServer(), a = {...defaultPlan(), lens: 50}, b = {...defaultPlan(), move: 'orbit'}, c = {...defaultPlan(), lens: 85};
  assert.deepEqual(await loadPlan(server.request, 'sh_1'), {plan: null, revision: 0, updatedAt: null, updatedBy: null, castOptions: [{code: '@CAST-01', name: 'Kael'}, {code: '@CAST-02', name: 'Mira'}]});
  const first = await savePlan(server.request, 'sh_1', a, 0);
  assert.deepEqual([first.ok, first.saved.revision, first.saved.plan], [true, 1, a]);
  assert.deepEqual(server.calls.at(-1), {path: '/shots/sh_1/previs-plan', method: 'PUT', body: {plan: a}, headers: {'If-Match': '"0"'}});
  assert.equal((await savePlan(server.request, 'sh_1', b, 1)).saved.revision, 2, 'someone else saves revision 2');
  const lost = await savePlan(server.request, 'sh_1', c, 1);
  assert.equal(lost.ok, false);
  assert.deepEqual([lost.conflict.currentRevision, lost.conflict.stored.plan], [2, b], 'the conflict carries what is stored now');
  assert.deepEqual(server.shots.get('sh_1').plan, b, 'a refused save wrote nothing');
  const over = await savePlan(server.request, 'sh_1', c, lost.conflict.currentRevision);
  assert.deepEqual([over.ok, over.saved.revision, over.saved.plan], [true, 3, c], 'saving over it names the revision stored now');
  const retried = await savePlan(server.request, 'sh_1', c, 2);
  assert.deepEqual([retried.ok, retried.saved.revision], [true, 3], 'a retry of a save that already landed is not a conflict');
  await assert.rejects(savePlan(server.request, 'sh_other/x', a, 0), error => error.code === 'DRAMA_NOT_FOUND', 'other failures are thrown, not settled');
});

test('the stage reads every stored plan once, newer revisions again, and the shot on stage for its cast codes', () => {
  const shot = (rid, revision, stored, shotId = 'sh_' + rid) => ({rid, shotId, previsRevision: revision, previsStored: stored});
  const shots = [shot('a', 2, true), shot('b', 0, false), shot('c', 3, false), shot('d', 1, true), {rid: 'e', shotId: null, previsRevision: null, previsStored: false}];
  assert.deepEqual(plansToLoad(shots, {}, 'b').map(s => s.rid), ['a', 'b', 'd'], 'stored plans and the shot on stage');
  assert.deepEqual(plansToLoad(shots, {a: {revision: 2}, b: {revision: 0}, d: {revision: 0}}, 'b').map(s => s.rid), ['d'], 'only what moved on');
  assert.deepEqual(plansToLoad(shots, {a: {revision: 5}}, 'e').map(s => s.rid), ['d'], 'a newer revision saved here is not read back; a sheet row has nothing stored');
  assert.deepEqual([storable(shots[0]), storable(shots[4]), storable({shotId: 'sh_x', previsRevision: null})], [true, false, false]);
  assert.deepEqual(storedPlan(null), {plan: null, revision: 0, updatedAt: null, updatedBy: null, castOptions: []});
});

test('a browser draft remembers the revision it started from; drafts from before stored plans started from nothing', () => {
  const plan = {...defaultPlan(), lens: 85};
  assert.deepEqual(readDraft({plan, base: 4}), {plan, base: 4});
  assert.deepEqual(readDraft(plan), {plan, base: 0}, 'a bare plan is a legacy draft');
  for (const value of [null, undefined, 'plan', 3, [plan], {plan, base: -1}, {plan, base: '2'}, {plan}, {plan: [plan], base: 1}, {plan: null, base: 0}]) {
    assert.equal(readDraft(value), null, JSON.stringify(value));  // a damaged draft is dropped, never trusted with a revision
  }
});

test('plans compare as data, whatever the key order or undefined values', () => {
  assert.ok(samePlan({lens: 35, keys: null, mark: [0, 1]}, {mark: [0, 1], keys: null, lens: 35}));
  assert.ok(samePlan({lens: 35, easing: undefined}, {lens: 35}));
  assert.ok(samePlan(null, undefined));
  assert.ok(!samePlan({lens: 35, keys: null}, {lens: 35}), 'a null key is still a key');
  assert.ok(!samePlan({mark: [0, 1]}, {mark: [1, 0]}));
  assert.ok(!samePlan(defaultPlan(), null));
});

test('Sync slate text writes the plan as Optical Rig and Camera Motion, which read back as the same plan', () => {
  const plan = {...defaultPlan(), lens: 85, move: 'orbit', seconds: 6};
  const synced = slateFromPlan(plan, {rig: 'ARRI Alexa 65 / 35mm Anamorphic f/1.4'});
  assert.deepEqual(synced, {opticalRig: 'ARRI Alexa 65 / 85mm Anamorphic f/1.4', cameraMotion: describePlan(plan)});
  assert.equal(synced.cameraMotion, 'Orbit around him from his left to his right, 85mm, 6 s');
  assert.equal(slateFromPlan(plan, {rig: 'DV Camcorder / Clean Sharp'}).opticalRig, 'DV Camcorder / Clean Sharp / 85mm');
  assert.equal(slateFromPlan(plan, {rig: '  '}).opticalRig, '85mm');
  assert.equal(slateFromPlan(plan).opticalRig, '85mm');
  for (const move of ['pushin', 'pullout', 'orbit', 'crane', 'track', 'static']) {
    for (const lens of [24, 35, 50, 85]) {
      const text = slateFromPlan({...defaultPlan(), move, lens}, {rig: 'RED V-Raptor / 50mm Prime f/1.8'}), back = planFromSlate({motion: text.cameraMotion, rig: text.opticalRig});
      assert.deepEqual([back.move, back.lens], [move, lens], `${move} ${lens}mm`);
    }
  }
  assert.equal(slateFromPlan({...defaultPlan(), keys: [[0, [1, 1, 1], [0, 0, 0]], [96, [2, 1, 1], [0, 0, 0]]]}).cameraMotion, 'Custom camera path, 35mm, 4 s');
});

test('who is on set carries a cast code: the actor and each character, once per shot', () => {
  const plan = {...defaultPlan(), mark: [0.5, -1]};
  const coded = setCastCode(plan, 'actor', '@CAST-01');
  assert.equal(coded.code, '@CAST-01');
  assert.ok(!('code' in setCastCode(coded, 'actor', '')), 'an empty choice takes the code off');
  const joined = addCastMember(coded, '@CAST-02');
  assert.deepEqual(joined.cast, [{code: '@CAST-02', mark: [1.7, -1]}], 'a character joins a step to the right of the actor');
  const third = addCastMember(joined, '@CAST-03');
  assert.deepEqual(third.cast[1], {code: '@CAST-03', mark: [2.9, -1]}, 'and the next one beside the last');
  assert.deepEqual(codesOnSet(third), ['@CAST-01', '@CAST-02', '@CAST-03']);
  assert.deepEqual(setCastCode(third, 1, '@CAST-04').cast[1], {code: '@CAST-04', mark: [2.9, -1]});
  assert.deepEqual(setCastCode(third, 0, '').cast[0], {mark: [1.7, -1]});
  assert.equal(setCastCode(third, 7, '@CAST-05'), third, 'nobody there, nothing changes');
  assert.deepEqual(removeCastMember(third, 0).cast.map(member => member.code), ['@CAST-03']);
  assert.deepEqual(codesOnSet({...defaultPlan(), cast: [{mark: [0, 0]}]}), []);
  const far = addCastMember({...defaultPlan(), mark: [DOME.x + DOME.radius - 0.5, DOME.z]}, '@CAST-02').cast[0].mark;
  assert.ok(Math.hypot(far[0] - DOME.x, far[1] - DOME.z) <= DOME.radius - 0.3 + 1e-9, 'a new mark stays inside the dome');
});

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.stored-plan-'));
  const result = await build({stdin: {contents: "export {default as PrevisStage} from './src/previs/PrevisStage.jsx'; export {setLocale} from './src/i18n/index.js';",
    resolveDir: root, sourcefile: 'stored-plan.jsx', loader: 'jsx'}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive: true, force: true});});
const stage = props => renderToStaticMarkup(React.createElement(components.PrevisStage, {slug: 'demo', writable: true, busy: false, onRender: async () => true, ...props}));
const shotOf = extra => ({rid: 'a', r: 0, shot: 'S01', slate: {motion: 'Static Tripod', rig: '35mm', action: 'Kael waits'}, previs: null, keyframe: null,
  matteCol: -1, skeletonCol: -1, setAsset: null, ...extra});

test('a story shot offers Save plan and says where its plan is; a sheet row keeps the browser-only stage', () => {
  const fresh = stage({shots: [shotOf({shotId: 'sh_demo_a', previsRevision: 0, previsStored: false})]});
  assert.match(fresh, /title="Store this shot&#x27;s 3D plan in the project, where the whole crew sees it">Save plan<\/button>/);
  assert.match(fresh, /Not saved in the project yet\./);
  assert.doesNotMatch(fresh, /<button[^>]*disabled=""[^>]*>Save plan</, 'the plan on stage can be stored as it is');
  assert.match(fresh, /title="Write 35mm into Optical Rig and “Locked-off over-the-shoulder shot, 35mm, 4 s” into Camera Motion">Sync slate text<\/button>/,
    'the slate says Static Tripod, the plan reads as a locked-off shot');
  const loading = stage({shots: [shotOf({shotId: 'sh_demo_a', previsRevision: 2, previsStored: true})]});
  assert.match(loading, /Loading the saved plan…/);
  assert.match(loading, /<button type="button" class="primary previs-render" disabled="">Render previs<\/button>/, 'no render over a plan not read yet');
  assert.match(loading, /<fieldset class="previs-fields" disabled="">/, 'and no edit that would start from the wrong plan');
  const sheet = stage({shots: [shotOf({})]});
  assert.doesNotMatch(sheet, /Save plan|Sync slate text|saved in the project|Saved in the project/);
  assert.match(sheet, /<button type="button" class="primary previs-render">Render previs<\/button>/);
  const viewer = stage({shots: [shotOf({shotId: 'sh_demo_a', previsRevision: 0, previsStored: false})], writable: false});
  assert.doesNotMatch(viewer, /Save plan|Sync slate text/, 'a viewer reads where the plan is but cannot write it');
  assert.match(viewer, /Not saved in the project yet\./);
});

test('the stored-plan messages read in Traditional Chinese', () => {
  components.setLocale('zh-TW');
  try {
    const html = stage({shots: [shotOf({shotId: 'sh_demo_a', previsRevision: 0, previsStored: false})]});
    for (const text of ['儲存計畫', '還沒存進專案。', '同步分鏡表文字']) assert.ok(html.includes(text), text);
  } finally {components.setLocale('en');}
});
