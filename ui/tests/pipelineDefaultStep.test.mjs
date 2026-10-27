// SPEC_20 R44-7: several pipeline steps write a shot's Keyframe and Cinema Shot; the column's default step ("primary") decides
// which one a shot's Run buttons, Re-shoot and Run Pipeline use, and the Pipeline inspector sets it.
import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {join, dirname, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {studioRunInput} from '../src/studioModel.js';
import {columnRivals, redrawStart, sameOutput, setDefaultStep} from '../src/flowModel.js';
import {setLocale} from '../src/i18n/index.js';

// The pipeline a new production gets (local_workers.STUDIO_LANES): the main lane, OpenJutsu, the previs lane and the layout lane.
const shot = (id, title, capability, col, extra = {}) => ({id, title, capability, scope:'rows', row_source:{tab_key:'cinema-studio'},
  target:{tab_key:'cinema-studio', table_id:'shots', column_id:'c' + col, col_index:col}, limb_id:'w-' + id, ...extra});
const lab = (id, title, col, extra = {}) => ({id, title, capability:'video_gen', scope:'rows', row_source:{tab_key:'openjutsu-lab'},
  target:{tab_key:'openjutsu-lab', table_id:'lab', column_id:'l' + col, col_index:col}, ...extra});
const production = (marked = true) => ({revision:3, definition:{nodes:[
  {id:'image', title:'Soul Cast References', capability:'image_gen', scope:'rows', row_source:{tab_key:'soul-cast'}, target:{tab_key:'soul-cast', table_id:'cast', column_id:'r3', col_index:3}},
  shot('keyframe', 'Shot Keyframe', 'image_gen', 4, marked ? {primary:true} : {}),
  shot('cinema', 'Cinema Shot', 'video_gen', 5, marked ? {primary:true} : {}),
  {id:'assemble', title:'Director Cut', capability:'media_assemble', scope:'aggregate', row_source:{tab_key:'cinema-studio'}, target:{tab_key:'director-brief', kind:'doc', mode:'append'}},
  lab('v2v', 'OpenJutsu Remaster', 4), {...lab('split', 'Source / Remaster Comparison', 5), capability:'media_assemble'},
  shot('motion', 'Previs Motion Pass', 'video_gen', 5), shot('lookkey', 'Look Key', 'image_gen', 4), shot('look', 'Look Pass', 'video_gen', 5),
  shot('layoutkey', 'Layout Key', 'image_gen', 4), shot('layout', 'Layout Render', 'video_gen', 5),
], edges:[['keyframe', 'cinema'], ['cinema', 'assemble'], ['v2v', 'split'], ['motion', 'lookkey'], ['lookkey', 'look'], ['layoutkey', 'layout']].map(([source, target]) => ({source, target}))}});
const columnIds = ['c0', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7'];
const scope = {tabKey:'cinema-studio', tableId:'shots', columnIds, rowIds:['r1']};
// The calls SheetWorkspace makes: a stage's Run (and Re-shoot Take), Run Pipeline on selected shots, the 3D Stage's lane buttons.
const run = (flow, column, extra = {}) => studioRunInput(flow, {...scope, singleStep:true, capability:column === 4 ? 'image_gen' : 'video_gen', col_index:column, ...extra});
const runPipeline = (flow, rowIds = ['r1', 'r2']) => studioRunInput(flow, {...scope, rowIds});
const motionStage = flow => studioRunInput(flow, {...scope, singleStep:true, capability:'video_gen', match:node => node.id === 'motion' || /previs motion/i.test(node.title || '')});
const layoutStage = flow => studioRunInput(flow, {...scope, capability:'image_gen', match:node => node.id === 'layoutkey' || /layout key/i.test(node.title || '')});

test('a new production shoots a shot on its main lane: Run, Re-shoot and Run Pipeline take the default steps', () => {
  const flow = production();
  assert.deepEqual(run(flow, 4), {execution_mode:'single_step', node_id:'keyframe', input_mode:'current_sources', sample_row_id:'r1', definition_revision:3});
  assert.equal(run(flow, 5).node_id, 'cinema');
  assert.deepEqual(runPipeline(flow), {target_tab:'cinema-studio', row_ids:['r1', 'r2'], definition_revision:3, start_node_id:'keyframe'});
  // A capability start without a single step prefers the default step too.
  assert.equal(studioRunInput(flow, {...scope, capability:'video_gen', col_index:5}).start_node_id, 'cinema');
  // The 3D Stage's lane buttons name their own step, as before.
  assert.equal(motionStage(flow).node_id, 'motion');
  assert.equal(layoutStage(flow).start_node_id, 'layoutkey');
  // A lane whose default is downstream of its first step still starts there.
  const cinemaOnly = structuredClone(flow); delete cinemaOnly.definition.nodes.find(node => node.id === 'keyframe').primary;
  assert.equal(runPipeline(cinemaOnly).start_node_id, 'keyframe');
});

test('without one default the action is still refused, naming the competing steps and how to mark one', async () => {
  const flow = production(false);
  assert.throws(() => run(flow, 4), {message:'3 pipeline steps write this column: “Shot Keyframe”, “Look Key”, “Layout Key”. Open Pipeline, select the one to use and turn on “Default step for this column”.'});
  assert.throws(() => run(flow, 5), /4 pipeline steps write this column: “Cinema Shot”, “Previs Motion Pass”, “Look Pass”, “Layout Render”/);
  assert.throws(() => runPipeline(flow), {message:'Run Pipeline starts at one lane, but 3 lanes start on this page: “Shot Keyframe”, “Previs Motion Pass”, “Layout Key”. Open Pipeline and turn on “Default step for this column” on a step of the lane to run.'});
  await setLocale('zh-TW');
  try {
    assert.throws(() => run(flow, 4), {message:'有 3 個管線步驟寫這一欄：「Shot Keyframe」、「Look Key」、「Layout Key」。請到管線選好要用的那一個，打開「這一欄的預設步驟」。'});
  } finally { await setLocale('en'); }
  // Two defaults in one column (the server refuses saving that) are no default: never a silent pick.
  const twice = production(); twice.definition.nodes.find(node => node.id === 'lookkey').primary = true;
  assert.throws(() => run(twice, 4), /3 pipeline steps write this column/);
  // Two lanes holding defaults, or a default only on another page: Run Pipeline names the lanes and refuses.
  const lanes = production(); lanes.definition.nodes.find(node => node.id === 'keyframe').primary = false; lanes.definition.nodes.find(node => node.id === 'lookkey').primary = true;
  assert.equal(run(lanes, 4).node_id, 'lookkey');
  assert.throws(() => runPipeline(lanes), /2 lanes start on this page: “Shot Keyframe”, “Previs Motion Pass”/);
  const elsewhere = production(false); elsewhere.definition.nodes[0].primary = true;
  assert.throws(() => runPipeline(elsewhere), /3 lanes start on this page/);
  // A lane action whose predicate matches several steps is refused as before; the default plays no part in it.
  assert.throws(() => studioRunInput(production(), {...scope, singleStep:true, capability:'image_gen', col_index:4, match:node => node.capability === 'image_gen'}), /No unambiguous pipeline step/);
  // Nothing writes the column: the earlier refusal.
  assert.throws(() => run(production(), 7), /No unambiguous pipeline step/);
});

test('the Object Swap row filter decides before the default step', () => {
  const flow = production();
  flow.definition.nodes.find(node => node.id === 'v2v').primary = true;
  flow.definition.nodes.push(lab('swap', 'OpenJutsu Swap', 4, {row_source:{tab_key:'openjutsu-lab', table_id:'lab', status_col:1, status:['Object Swap']}}));
  const labScope = {tabKey:'openjutsu-lab', tableId:'lab', columnIds:['l0', 'l1', 'l2', 'l3', 'l4'], rowIds:['v1'], singleStep:true, capability:'video_gen', col_index:4};
  assert.equal(studioRunInput(flow, {...labScope, row:['VFX-02', 'Object Swap']}).node_id, 'swap');
  assert.equal(studioRunInput(flow, {...labScope, row:['VFX-01', 'Motion Transfer']}).node_id, 'v2v');
});

test('the editor finds the steps sharing a column and keeps one default per column', () => {
  const {definition} = production(false), node = id => definition.nodes.find(item => item.id === id);
  assert.deepEqual(columnRivals(definition, node('keyframe')).map(item => item.id), ['lookkey', 'layoutkey']);
  assert.deepEqual(columnRivals(definition, node('image')), []);
  assert.deepEqual(columnRivals(definition, node('assemble')), []);  // a document output is no column
  assert.ok(sameOutput({tab_key:'s', column_id:'k', col_index:1}, {tab_key:'s', column_id:'k', col_index:4}));
  assert.ok(sameOutput({tab_key:'s', table_id:'t', col_index:4}, {tab_key:'s', col_index:4}));
  assert.ok(!sameOutput({tab_key:'s', table_id:'t', col_index:4}, {tab_key:'s', table_id:'u', col_index:4}));
  assert.ok(!sameOutput({tab_key:'s', column_id:'k', col_index:4}, {tab_key:'s', column_id:'j', col_index:4}));
  let next = setDefaultStep(definition, 'lookkey', true);
  assert.deepEqual(next.nodes.filter(item => item.primary).map(item => item.id), ['lookkey']);
  next = setDefaultStep(next, 'keyframe', true);
  next = setDefaultStep(next, 'cinema', true);
  assert.deepEqual(next.nodes.filter(item => item.primary).map(item => item.id), ['keyframe', 'cinema']);
  assert.ok(!('primary' in next.nodes.find(item => item.id === 'lookkey')));
  next = setDefaultStep(next, 'keyframe', false);
  assert.deepEqual(next.nodes.filter(item => 'primary' in item).map(item => item.id), ['cinema']);
  assert.equal(definition.nodes.some(item => 'primary' in item), false);  // the definition it was given is unchanged
  // "Open in Pipeline" from a shot's column starts at the column's default step.
  const selection = {target_tab:'cinema-studio', capability:'image_gen', col_index:4};
  assert.equal(redrawStart(setDefaultStep(definition, 'layoutkey', true), selection), 'layoutkey');
  assert.equal(redrawStart(definition, selection), 'keyframe');
});

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let temporary, components;
before(async () => {
  temporary = await mkdtemp(join(root, 'tests/.default-step-render-'));
  const result = await build({stdin:{contents:"export {FlowInspector} from './src/FlowPanels.jsx';", resolveDir:root, sourcefile:'default-step-render.jsx', loader:'jsx'},
    bundle:true, write:false, platform:'node', format:'esm', jsx:'automatic', packages:'external', loader:{'.css':'empty'}});
  const output = join(temporary, 'components.mjs');
  await writeFile(output, result.outputFiles[0].text);
  components = await import(pathToFileURL(output));
});
after(async () => {if (temporary) await rm(temporary, {recursive:true, force:true});});

test('the step inspector offers "Default step for this column" only where another step writes that column', () => {
  const definition = production().definition;
  const shots = {tableId:'shots', name:'Shots', headers:['Shot', 'Prompt', 'Status', 'Refs', 'Keyframe', 'Cinema Shot'], rows:[], table:{attrs:{column_ids:columnIds}}};
  const render = (id, flowDefinition = definition) => renderToStaticMarkup(React.createElement(components.FlowInspector, {
    selected:flowDefinition.nodes.find(node => node.id === id), selectedId:id, definition:flowDefinition, tabs:[{key:'cinema-studio', title:'Cinema Studio', surface_type:'sheet'}],
    tab:{key:'comfy-pipeline'}, workers:[], agents:[], writable:true, busy:false, sourceDoc:null, sourceTables:[], sourceTable:null, targetTables:[shots], targetTable:shots,
    sourceKey:'cinema-studio', targetKey:'cinema-studio', samples:[], sampleRow:'', tasks:[], update() {}, change() {}, connect() {}}));
  const keyframe = render('keyframe');
  assert.match(keyframe, /<label class="flow-check"><input type="checkbox" checked=""\/>Default step for this column<\/label>/);
  assert.match(keyframe, /Also written by “Look Key”, “Layout Key”\./);
  assert.match(render('lookkey'), /<label class="flow-check"><input type="checkbox"\/>Default step for this column<\/label>/);
  const alone = {...definition, nodes:definition.nodes.filter(node => !['lookkey', 'layoutkey'].includes(node.id))};
  assert.doesNotMatch(render('keyframe', alone), /Default step for this column/);
});
