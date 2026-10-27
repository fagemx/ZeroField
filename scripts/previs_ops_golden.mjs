// Golden files for the 3D operations solver (SPEC_20 R27): the JS solver's own output, checked in.
//
//   node scripts/previs_ops_golden.mjs           compare tests/fixtures/previs_ops_golden.json with the solver; exit 1 on a difference
//   node scripts/previs_ops_golden.mjs --write   accept the solver's current output (review the diff before committing)
//
// The Python tests read the same file: every solved plan must pass project_docs/story_previs.validate and the Python
// consistency check, and every invalid case must be refused by project_assistant/previs_ops.validate_ops at the same
// path as the JS validator. ui/tests/previsOps.test.mjs re-solves every case, and scripts/previs_headless_check.py solves
// them again in the headless browser, so the server, the 3D Stage and this file cannot drift apart.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { OPS_VERSION, OpsError, solveRequest } from '../ui/src/previs/ops.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FILE = path.join(ROOT, 'tests', 'fixtures', 'previs_ops_golden.json');
const CODES = ['@CAST-01', '@CAST-02', '@CAST-03'];
const OBSERVATORY = { set: 'observatory', move: 'pushin', lens: 35, action: 'turnreach', facing: 'console', mood: 'grey', seconds: 4 };
const SEED = { slate: { motion: 'Slow Dolly Push-In', rig: 'ARRI Alexa 65 / 35mm Anamorphic f/1.4', action: '@CAST-01 turns from the glass to the brass dial.' }, previsPlan: null, setAsset: null };
const WALK = { ...OBSERVATORY, action: 'stand', seconds: 8, code: '@CAST-01', use: [
  { skill: 'walkTo', args: { from: [0, -2.2], to: [0, 0] } }, { skill: 'standIdle', frames: 24 }, { skill: 'turnLook', args: { heading: 0 } }] };

const CASES = [
  { id: 'front-closeup-from-the-seed', note: 'Nothing stored: the slate seeds the plan; the first code becomes the actor; a close push-in on the face.',
    input: { stored: null, shot: SEED, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-01', relativeTo: 'console', offset: [0, -0.55], facing: 'camera' },
      { op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'pushin', from: 'K1', to: 'K2' }] } },
  { id: 'two-shot-stored-plan', note: 'A stored plan with a named actor: he moves, a second person joins facing him, a low medium static shot.',
    input: { stored: { ...OBSERVATORY, code: '@CAST-01', mark: [0.4, -0.6], easing: [0.2, 0, 0.8, 1] }, shot: SEED, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-01', relativeTo: 'console_edge', offset: [0.1, -0.5], facing: 'room' },
      { op: 'place', cast: '@CAST-02', relativeTo: '@CAST-01', offset: [-0.4, -0.9], facing: '@CAST-01' },
      { op: 'camera', size: 'medium', angle: 'low', lens: 35, move: 'static' }] } },
  { id: 'triangle-full-orbit', note: 'Three people around the subject, the whole orbit K1 to K3, faces toward each other.',
    input: { stored: null, shot: { ...SEED, previsPlan: { set: 'observatory', action: 'stand', lens: 35, move: 'orbit', seconds: 6 } }, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-03', relativeTo: 'console', offset: [0, -0.5], facing: 'camera' },
      { op: 'place', cast: '@CAST-01', relativeTo: '@CAST-03', offset: [-0.75, 0.1], facing: '@CAST-02' },
      { op: 'place', cast: '@CAST-02', relativeTo: '@CAST-03', offset: [0.75, 0.1], facing: '@CAST-01' },
      { op: 'camera', size: 'medium', angle: 'eye', lens: 35, move: 'orbit', from: 'K1', to: 'K3' }] } },
  { id: 'parallax-crane-with-set-image', note: 'The parallax seed with the set image as its far card; placed at the near card; a crane from low.',
    input: { stored: null, shot: { slate: { motion: 'Crane Rise High-Angle', rig: '35mm', action: '@CAST-02 waves goodbye.' },
      previsPlan: { set: 'parallax', lens: 35, move: 'crane', action: 'stand', facing: 'console', seconds: 6 },
      setAsset: { id: 'SET-02', url: '/projects/api/golden/assets/pa_0123456789abcdef0123456789abcdef' } }, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-02', relativeTo: 'near', offset: [0, 0.6], facing: 'camera' },
      { op: 'camera', size: 'medium', angle: 'low', lens: 35, move: 'crane', from: 'K1', to: 'K2' }] } },
  { id: 'empty-stage-extreme-close', note: 'The empty stage: only the mark; an 85 mm extreme close-up held still.',
    input: { stored: { ...OBSERVATORY, set: 'empty', action: 'stand', figure: { build: 'woman' } }, shot: SEED, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-02', relativeTo: 'mark', offset: [0, 0], facing: 'room' },
      { op: 'camera', size: 'extreme_close', angle: 'eye', lens: 85, move: 'static', from: 'K1' }] } },
  { id: 'walk-retimed-and-tracked', note: 'An actor with skills keeps his facing and turns; his second acting beat moves; a lateral track.',
    input: { stored: WALK, shot: SEED, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [0.5, -0.3], facing: 'window' },
      { op: 'camera', size: 'full', angle: 'high', lens: 24, move: 'track' },
      { op: 'retime', beat: 2, at: 0.75 }] } },
  { id: 'kept-on-stage-and-pulled-in', note: 'A mark beyond the glass is kept on the stage; a wide high pull-out is pulled in under the dome.',
    input: { stored: null, shot: SEED, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [6, -7], facing: 'console' },
      { op: 'camera', size: 'wide', angle: 'overhead', lens: 24, move: 'pullout' }] } },
  { id: 'walk-in-toward-the-lens', note: 'A Walk in facing the lens walks 2.2 m toward the camera: the camera frames where he ends.',
    input: { stored: null, shot: { ...SEED, slate: { ...SEED.slate, action: '@CAST-01 walks in toward us.' } }, castCodes: CODES, ops: [
      { op: 'place', cast: '@CAST-01', relativeTo: 'console', offset: [0, -0.5], facing: 'camera' },
      { op: 'camera', size: 'close', angle: 'eye', lens: 35, move: 'pushin' }] } },
  { id: 'retime-only', note: 'Only a retime: nobody moves, the camera stays the stored one.',
    input: { stored: WALK, shot: SEED, castCodes: CODES, ops: [{ op: 'retime', beat: 3, at: 0.6 }] } },
];

// Each refused request and the path both validators must name.
const INVALID = [
  ['unknown-op', [{ op: 'teleport', cast: '@CAST-01' }], 'ops[0]'],
  ['extra-field', [{ op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'static', script: 'x' }], 'ops[0]'],
  ['missing-field', [{ op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [0, 0] }], 'ops[0]'],
  ['not-a-cast-code', [{ op: 'place', cast: 'Kael', relativeTo: 'mark', offset: [0, 0], facing: 'room' }], 'ops[0].cast'],
  ['off-the-cast-sheet', [{ op: 'place', cast: '@CAST-09', relativeTo: 'mark', offset: [0, 0], facing: 'room' }], 'ops[0].cast'],
  ['placed-twice', [{ op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [0, 0], facing: 'room' },
    { op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [1, 0], facing: 'room' }], 'ops[1].cast'],
  ['unknown-target', [{ op: 'place', cast: '@CAST-01', relativeTo: 'desk', offset: [0, 0], facing: 'room' }], 'ops[0].relativeTo'],
  ['relative-to-nobody', [{ op: 'place', cast: '@CAST-01', relativeTo: '@CAST-02', offset: [0, 0], facing: 'room' }], 'ops[0].relativeTo'],
  ['relative-to-self', [{ op: 'place', cast: '@CAST-01', relativeTo: '@CAST-01', offset: [0, 0], facing: 'room' }], 'ops[0].relativeTo'],
  ['offset-too-far', [{ op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [0, 9], facing: 'room' }], 'ops[0].offset'],
  ['offset-shape', [{ op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [0, 0, 1], facing: 'room' }], 'ops[0].offset'],
  ['facing-nobody', [{ op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [0, 0], facing: '@CAST-03' }], 'ops[0].facing'],
  ['facing-self', [{ op: 'place', cast: '@CAST-01', relativeTo: 'mark', offset: [0, 0], facing: '@CAST-01' }], 'ops[0].facing'],
  ['lens-not-in-lenses', [{ op: 'camera', size: 'close', angle: 'eye', lens: 40, move: 'static' }], 'ops[0].lens'],
  ['move-not-in-moves', [{ op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'dolly' }], 'ops[0].move'],
  ['size-unknown', [{ op: 'camera', size: 'cowboy', angle: 'eye', lens: 50, move: 'static' }], 'ops[0].size'],
  ['angle-unknown', [{ op: 'camera', size: 'close', angle: 'dutch', lens: 50, move: 'static' }], 'ops[0].angle'],
  ['key-out-of-move', [{ op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'pushin', from: 'K1', to: 'K3' }], 'ops[0].to'],
  ['key-backwards', [{ op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'orbit', from: 'K3', to: 'K1' }], 'ops[0].to'],
  ['static-two-keys', [{ op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'static', from: 'K1', to: 'K2' }], 'ops[0].to'],
  ['not-a-key', [{ op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'pushin', from: 'start', to: 'K2' }], 'ops[0].from'],
  ['two-cameras', [{ op: 'camera', size: 'close', angle: 'eye', lens: 50, move: 'static' },
    { op: 'camera', size: 'wide', angle: 'eye', lens: 24, move: 'static' }], 'ops[1]'],
  ['beat-not-in-plan', [{ op: 'retime', beat: 4, at: 0.5 }], 'ops[0].beat'],
  ['beat-twice', [{ op: 'retime', beat: 1, at: 0.2 }, { op: 'retime', beat: 1, at: 0.3 }], 'ops[1].beat'],
  ['at-outside-shot', [{ op: 'retime', beat: 1, at: 1.5 }], 'ops[0].at'],
  ['no-ops', [], 'ops'],
].map(([id, ops, path]) => ({ id, input: { stored: WALK, shot: SEED, castCodes: CODES.slice(0, 2), ops }, path }));

function build() {
  const cases = CASES.map(({ id, note, input }) => ({ id, note, input, expect: solveRequest(input) }));
  const invalid = INVALID.map(({ id, input, path: want }) => {
    try { solveRequest(input); } catch (error) {
      if (!(error instanceof OpsError)) throw error;
      if (error.path !== want) throw new Error(`${id}: the JS validator names ${error.path}, the golden file says ${want}`);
      return { id, input, path: error.path, message: error.message };
    }
    throw new Error(`${id}: the JS validator accepted it`);
  });
  return { schema: 'zerofield.previs_ops.golden/1', version: OPS_VERSION,
    note: 'Generated by node scripts/previs_ops_golden.mjs --write from ui/src/previs/ops.js (SPEC_20 R27). Review the diff before committing.',
    cases, invalid };
}

const golden = JSON.stringify(build(), null, 1) + '\n';
if (process.argv.includes('--write')) {
  fs.writeFileSync(FILE, golden);
  console.log(`wrote ${path.relative(ROOT, FILE)}`);
} else {
  const saved = fs.existsSync(FILE) ? fs.readFileSync(FILE, 'utf8').replace(/\r\n/g, '\n') : '';
  if (saved !== golden) { console.error(`${path.relative(ROOT, FILE)} differs from the solver; run with --write after reviewing.`); process.exit(1); }
  console.log('previs ops golden file matches the solver');
}
