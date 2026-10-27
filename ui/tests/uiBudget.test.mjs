// Control budgets (CozyClay's studio-control-count, SPEC_12): count the controls a screen shows before anything is
// opened, so a workbench cannot quietly grow standing buttons, duplicates or disabled ones with no reason.
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const uiRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let components, temporary;
before(async () => {
  temporary = await mkdtemp(join(uiRoot, 'tests/.budget-render-'));
  const result = await build({ stdin: { contents: "export {StudioTopBar} from './src/StudioShell.jsx'; export {default as PrevisStage} from './src/previs/PrevisStage.jsx'; export {ShotFilmView} from './src/ShotFilmPanel.jsx'; export {mergeTakes, filmNeighbors, filmSegments, filmSummary} from './src/takeModel.js';", resolveDir: uiRoot, sourcefile: 'budget-render.jsx', loader: 'jsx' },
    bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: { '.css': 'empty' } });
  const output = join(temporary, 'components.mjs'); await writeFile(output, result.outputFiles[0].text); components = await import(pathToFileURL(output));
});
after(async () => { if (temporary) await rm(temporary, { recursive: true, force: true }); });

// The controls visible on first paint: a closed <details> keeps its contents folded away.
const visible = html => html.replace(/<details(?![^>]*\sopen="")[^>]*>[\s\S]*?<\/details>/g, '');
const controls = html => [...visible(html).matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>|<(?:select|input)\b([^>]*)>/g)]
  .map(([, button, inner = '', field]) => {
    const attrs = button ?? field;
    return { disabled: /\sdisabled=""/.test(attrs), label: (attrs.match(/aria-label="([^"]*)"/)?.[1] || inner.replace(/<[^>]+>/g, '')).trim() };
  });

test('the studio top bar stands at most 9 controls, none twice; engineering tools live in Ctrl K', () => {
  const props = {project:{title:'The Last Signal'},episodes:[{episodeId:'ep_demo_01',title:'Episode 1'}],epId:'ep_demo_01',space:'stage',counts:{shots:8,review:2,missing:1,filmed:6,scriptDirty:true},onEpisode(){},onSpace(){},onCommand(){},film:{open:false,onToggle(){}}};
  const html = renderToStaticMarkup(React.createElement(components.StudioTopBar, props));
  const shown = controls(html);
  assert.ok(shown.length > 0 && shown.length <= 9, `${shown.length} standing controls: ${shown.map(c => c.label).join(', ')}`);
  const labels = shown.map(c => c.label).filter(Boolean);
  assert.equal(new Set(labels).size, labels.length, `R1: no duplicate control: ${labels.join(', ')}`);
  assert.ok(!shown.some(c => c.disabled), 'R3: no disabled control in the top bar');
  for (const folded of ['Toolbox', 'Open API', 'Agent Console', 'Asset Vault']) assert.ok(!html.includes(folded), `${folded} is a Ctrl K command`);
});

test('the 3D stage in the lens view shows no dead framing buttons, one way into the free camera, and stays in budget', () => {
  const shot = { rid: 'a', r: 0, shot: 'S01', slate: { motion: 'Static Tripod', rig: '35mm', action: 'Kael waits' }, previs: null, keyframe: null, matteCol: -1, skeletonCol: -1, setAsset: null };
  const html = renderToStaticMarkup(React.createElement(components.PrevisStage, { slug: 'demo', shots: [shot], writable: true, busy: false, onRender: async () => true, onMotion: () => {} }));
  const shown = controls(html), framing = html.match(/<legend>Framing<\/legend>([\s\S]*?)<\/fieldset>/)[1];
  assert.doesNotMatch(framing, /Set start|Set end|Use preset|Discard edits/, 'R2: start/end only in the free view, preset and discard only with a path or an edit');
  assert.doesNotMatch(framing, /disabled=""/, 'R3: no disabled framing button');
  assert.match(framing, /<button type="button">Frame Custom Path \(Free View\)<\/button>/);
  assert.doesNotMatch(html, />(PiP|Look through|Exit Look through)</, 'the PiP and Look through belong to the free and overhead views');
  assert.ok(shown.some(c => c.label === 'Export Keyframe Pack'));
  assert.ok(shown.length <= 40, `${shown.length} controls on the stage: ${shown.map(c => c.label).join(', ')}`);
});

test('SPEC_19 A7: the shot column has no approve button and no primary button, folds its rarer actions, and stays in budget', () => {
  const at = minute => new Date(Date.UTC(2026, 9, 27, 10, minute)).toISOString();
  const shots = Array.from({length: 8}, (_, i) => ({shotId: 'sh_demo_b' + i, rowId: 'b' + i, shotIndex: 'S0' + (i + 1), tabKey: 'cinema-studio', reviewStatus: i < 4 ? 'Approved' : 'Queued',
    selectedVideoUrl: i < 4 ? `/t/${i}.mp4` : null, selectedImageUrl: null, previsVideoUrl: null, trim: {in: 0, out: null}, adoption: null, takeSummary: {total: i < 4 ? 1 : 0, newSinceAdoption: 0}}));
  const adoption = {adopted: true, url: '/t/2.mp4', at: at(5), by: 'u1'};
  const takes = components.mergeTakes([{videoId: 'vd_1', url: '/t/2-1.mp4', createdAt: at(1)}, {videoId: 'vd_2', url: '/t/2.mp4', createdAt: at(3), selected: true}, {videoId: 'vd_3', url: '/t/2-3.mp4', createdAt: at(8)}], [], {status: 'Approved', adoption});
  const film = shots.map(shot => shot.shotId === 'sh_demo_b2' ? {...shot, adoption, takes} : shot);
  const props = {label: 'S03', state: 'new_take', newCount: 1, writable: true, disabled: false, menuItems: ['Mark as blocked', 'Remove from the cut', 'Open in table', 'Compare Versions', 'Replace Upload', 'Open in Pipeline ↗', 'Request Agent Revisions'].map((label, i) => ({id: 'm' + i, label, run() {}})),
    neighbours: components.filmNeighbors(film, 'sh_demo_b2'), segments: components.filmSegments(film), summary: components.filmSummary(film), currentId: 'sh_demo_b2', canAround: true, takes, hasFrame: true,
    trim: {url: '/t/2.mp4', trim: {in: 0, out: null}, source: null}, onTimeline() {}, notes: {messages: [], node: null}, cast: {count: 3, node: null}};
  const html = renderToStaticMarkup(React.createElement(components.ShotFilmView, props));
  assert.doesNotMatch(html, /class="primary|studio-primary|Approve/, 'no approve button, and the one primary button of the stage is the composer\'s Generate');
  assert.doesNotMatch(visible(html), /Mark as blocked|Remove from the cut|Open in table|Replace Upload|Open in Pipeline|Request Agent Revisions/, 'the rarer actions are in the folded … menu');
  const shown = controls(html).filter(c => !/ · [\d.]+ s$/.test(c.label));  // the progress bar's segments: one per shot, counted apart
  assert.ok(shown.length <= 16, `${shown.length} standing controls in the shot column: ${shown.map(c => c.label).join(', ')}`);
  const labels = shown.map(c => c.label).filter(Boolean);
  assert.equal(new Set(labels).size, labels.length, `no duplicate control: ${labels.join(', ')}`);
  assert.ok(!shown.some(c => c.disabled), 'no disabled control in a writable column');
  assert.equal((html.match(/class="film-seg /g) || []).length, 8, 'one segment per shot');
});

test('SPEC_19 A7: the Shot Stage no longer picks a primary action by status', async () => {
  const source = await readFile(join(uiRoot, 'src/SheetWorkspace.jsx'), 'utf8');
  assert.doesNotMatch(source, /primaryShotAction|studio-primary|stage\.primary_/);
  assert.match(source, /className=\{productionSheet\?undefined:"primary"\}/, 'the crew fill button stays outlined on a production sheet');
});
