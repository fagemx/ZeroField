import { t } from './i18n/index.js';
import { mediaOf, tablesOf } from './sheetModel.js';

export const OPTICAL_PRESETS = ['ARRI Alexa 65 / 35mm Anamorphic f/1.4', 'RED V-Raptor / 85mm Prime f/1.8', '35mm Film / Vintage Anamorphic', '16mm Bolex Vintage Film', 'DV Camcorder / Clean Sharp'];
export const MOTION_PRESETS = ['Slow Dolly Push-In', 'Tracking Shot', 'Static Tripod', 'Handheld Urgency', 'Crane Rise High-Angle', 'Drone Orbit 180°', 'Rack Focus', 'Whip Pan', 'POV'];
export const JUTSU_PRESETS = ['Motion Transfer', 'Object Swap'];
export function assetReferences(row) {
  return [...new Set((row.cells.map(cell => String(cell?.value || '')).join(' ').match(/@?\b(?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?\b/gi) || []).map(id => id.replace(/^@/, '').replace('#', ':').toUpperCase()))];
}
function stageRole(label) {
  if (/source.*video|driving.*video|previs|blockout/i.test(label)) return 0;
  if (/first\s*frame/i.test(label)) return 1;
  if (/motion\s*structure/i.test(label)) return 2;
  if (/anchor.*frame|key\s*frame/i.test(label)) return 3;
  if (/split|side.by.side|comparison/i.test(label)) return 5;
  if (/remaster|cinema\s*shot|output/i.test(label)) return 4;
  return null;
}
// Bench column for a media stage: footage in, control passes, the produced shot/remaster and its comparison out.
export function benchGroup(label) {
  const role = stageRole(label);
  return role === 0 ? 'input' : role >= 4 ? 'output' : 'control';
}
// A shot's stages as bench columns and the links between them: one source fans out to every control pass,
// several passes merge into the first output, and outputs chain (remaster -> split-screen).
export function benchLinks(stages) {
  const lane = { input: [], control: [], output: [] };
  for (const stage of stages) lane[benchGroup(stage.label)].push(stage);
  const order = ['input', 'control', 'output'].filter(key => lane[key].length), links = [];
  order.slice(1).forEach((key, k) => {
    const prev = lane[order[k]], targets = key === 'output' || prev.length > 1 ? [lane[key][0]] : lane[key];
    for (const from of prev) for (const to of targets) links.push([from, to]);
  });
  if (order.at(-1) === 'output') lane.output.slice(1).forEach((stage, j) => links.push([lane.output[j], stage]));
  return { lane, order, links };
}
export function mediaStages(parsed, row) {
  const types = parsed.table.attrs.column_types || [];
  const stages = parsed.headers.flatMap((label, column) => {
    const value = row.cells[column]?.value || '', media = mediaOf(value, types[column]);
    if (!['image','video'].includes(types[column]) && !['image','video'].includes(media?.kind)) return [];
    return [{column, label, type: media?.kind === 'asset' ? types[column] : media?.kind || types[column] || 'image', value, media}];
  });
  // Imported/custom media keep their original slots; recognized studio stages follow the reference pack.
  const ordered = stages.filter(stage => stageRole(stage.label) !== null).sort((a,b) => stageRole(a.label) - stageRole(b.label) || a.column - b.column);
  let next = 0;
  return stages.map(stage => stageRole(stage.label) === null ? stage : ordered[next++]);
}
export function buildAssetLookup(documents) {
  const lookup = {};
  for (const tab of documents) for (const table of tablesOf(tab.doc, tab.values || {})) for (const row of table.rows) {
    const values = row.cells.map(cell => String(cell?.value || '').trim());
    const at = values.findIndex(value => /^@?(?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][a-z0-9_-]+)?$/i.test(value));
    if (at < 0) continue;
    const id = values[at], name = /^(!?\[|https?:|\/projects\/)/.test(values[at + 1] || '') ? '' : (values[at + 1] || '').slice(0, 60);
    const stage = mediaStages(table, row).find(item => item.media);
    const key = id.replace(/^@/, '').replace('#', ':').toUpperCase();
    lookup[key] = {id:key, name, tabKey:tab.key, rowId:row.rid, ...(stage || {})};
  }
  for (const [id, asset] of Object.entries(lookup)) {
    const base = lookup[id.split(':')[0]];
    if (id.includes(':') && !asset.media && base?.media) lookup[id] = {...base, ...asset, value:base.value, media:base.media, type:base.type};
  }
  return lookup;
}
export function resolveAssetReference(id, lookup) {
  return {...(lookup[id] || lookup[id.split(':')[0]] || {}), id};
}
export function assetVariants(id, lookup) {
  const base = id.split(':')[0];
  return Object.keys(lookup).filter(key => key === base || key.startsWith(base + ':'));
}
export function presetsFor(header, assetIds = []) {
  if (/motion|movement/i.test(header)) return MOTION_PRESETS;
  if (/optical|rig|lens|camera(?!\s*motion)/i.test(header)) return OPTICAL_PRESETS;
  if (/jutsu|mode/i.test(header)) return JUTSU_PRESETS;
  if (/prompt|cast|reference|asset/i.test(header)) return assetIds.map(id => '@' + id);
  return [];
}
const PRESET_KEYS = {
  "ARRI Alexa 65 / 35mm Anamorphic f/1.4": "arriAlexa65",
  "RED V-Raptor / 85mm Prime f/1.8": "redVRaptor",
  "35mm Film / Vintage Anamorphic": "film35",
  "16mm Bolex Vintage Film": "bolex16",
  "DV Camcorder / Clean Sharp": "dvCamcorder",
  "Slow Dolly Push-In": "slowDollyPushIn",
  "Tracking Shot": "trackingShot",
  "Static Tripod": "staticTripod",
  "Handheld Urgency": "handheldUrgency",
  "Crane Rise High-Angle": "craneRise",
  "Drone Orbit 180°": "droneOrbit",
  "Rack Focus": "rackFocus",
  "Whip Pan": "whipPan",
  "POV": "pov",
  "Motion Transfer": "motionTransfer",
  "Object Swap": "objectSwap"
};
export function presetLabel(value) { return PRESET_KEYS[value] ? t("studioPresets." + PRESET_KEYS[value]) : value; }
export function applyPreset(value, preset) {
  if (!preset.startsWith('@')) return preset;
  return value.includes(preset) ? value : [value.trim(), preset].filter(Boolean).join(' ');
}

// Single-step uses the node's saved source/output. Never silently broaden a cell action.
export function studioRunInput(flow, {tabKey, tableId, columnIds = [], rowIds, singleStep, capability, col_index}) {
  if (!rowIds.length || rowIds.length > 200 || new Set(rowIds).size !== rowIds.length) throw new Error(t('studio.invalidRows'));
  const nodes = flow.definition?.nodes || [];
  const sameTable = target => target?.tab_key === tabKey && (!target.table_id || target.table_id === tableId);
  const preparedStage = Number.isInteger(col_index) && ['image_gen','video_gen'].includes(capability);
  const candidates = nodes.filter(node => sameTable(node.target) && (!capability || node.capability === capability || preparedStage && node.capability === 'media_assemble') &&
    (col_index == null || (node.target.column_id ? node.target.column_id === columnIds[col_index] : node.target.col_index === col_index)));
  if (singleStep) {
    const matching = candidates.filter(node => node.scope === 'rows'
      ? node.row_source?.tab_key === tabKey && (!node.row_source.table_id || node.row_source.table_id === tableId)
      : node.scope === 'once' && node.target.row_id === rowIds[0] && !node.row_source);
    if (rowIds.length !== 1 || matching.length !== 1) throw new Error(t('studio.noSafeStep'));
    return {execution_mode:'single_step', node_id:matching[0].id, input_mode:'current_sources', sample_row_id:rowIds[0], definition_revision:flow.revision};
  }
  const relevant = nodes.filter(node => node.row_source ? node.row_source.tab_key === tabKey && (!node.row_source.table_id || node.row_source.table_id === tableId) : sameTable(node.target));
  if (!relevant.length) throw new Error(t('studio.noSafeStep'));
  const relevantIds = new Set(relevant.map(node => node.id));
  const roots = relevant.filter(node => !(flow.definition.edges || []).some(edge => edge.target === node.id && relevantIds.has(edge.source)));
  const start = capability ? (candidates.length === 1 ? candidates[0] : null) : roots.length === 1 ? roots[0] : null;
  if (!start) throw new Error(t('studio.noSafeStep'));
  return {target_tab:tabKey, row_ids:[...rowIds], definition_revision:flow.revision, start_node_id:start.id};
}
export async function queueStudioRun(api, base, input, {tabKey, revision} = {}) {
  const preflight = await api.post(base + '/preflight', input);
  if (!preflight.ready) throw new Error(preflight.errors?.[0]?.message || t('studio.preflightAttention'));
  if (tabKey in (preflight.source_revisions || {}) && preflight.source_revisions[tabKey] !== revision) throw new Error(t('studio.sourceChanged'));
  return api.post(base + '/runs', {...input, source_revisions:preflight.source_revisions});
}
