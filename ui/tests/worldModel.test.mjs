import test from 'node:test';
import assert from 'node:assert/strict';
import { assetUses, activeItem, baseCode, bySlate, restoredWorld, rememberWorld, sceneFilter, UNSCENED, worldCounts, worldFacets, worldGroups, worldItems } from '../src/worldModel.js';

const asset = (code, type, image, extra = {}) => ({assetId:'as_' + code, assetCode:code, name:code, prompt:'', type, isDefault:true, selectedImageUrl:image, ...extra});
const assets = [asset('CAST-01', 'CHARACTER', '/k.png'), asset('CAST-02', 'CHARACTER', null), asset('SET-01', 'SCENE', '/o.png'), asset('PROP-01', 'PROP', null)];
const shot = (index, refs, scene) => ({shotId:'sh_' + index, shotIndex:index, assets:refs, sceneId:scene});
const shots = [shot('S10', ['SET-01'], 'sc2'), shot('S02', ['CAST-01', 'SET-01'], 'sc1'), shot('S01', ['CAST-01:NIGHT'], 'sc1'), shot('S03', [], 'sc1')];

test('an asset is used by the shots that name it or one of its looks, in slate order, across their scenes', () => {
  assert.equal(baseCode('cast-01:night'), 'CAST-01');
  const kael = assetUses(assets[0], shots);
  assert.deepEqual(kael.shots.map(s => s.shotIndex), ['S01', 'S02']);
  assert.deepEqual(kael.sceneIds, ['sc1']);
  const set = assetUses(assets[2], shots);
  assert.deepEqual(set.shots.map(s => s.shotIndex), ['S02', 'S10'], 'S10 sorts after S02, not after S1');
  assert.deepEqual(set.sceneIds, ['sc1', 'sc2']);
  assert.deepEqual(assetUses(assets[1], shots), {shots:[], sceneIds:[]});
  assert.deepEqual(assetUses(assets[0], [{shotIndex:'S1', assets:['CAST-010']}]).shots, [], 'CAST-010 is not CAST-01');
  assert.deepEqual(assetUses(assets[0], [{shotIndex:'VFX-01', assets:['CAST-01']}]).sceneIds, [], 'a shot without a scene adds none');
  assert.deepEqual(['S10', 'S2', 'S1'].map(shotIndex => ({shotIndex})).sort(bySlate).map(s => s.shotIndex), ['S1', 'S2', 'S10'], 'slate order is natural, not alphabetical');
});

test('items know their use and whether they still need an image; counts and facets follow', () => {
  const items = worldItems(assets, shots);
  assert.deepEqual(items.map(item => [item.assetCode, item.uses.length, item.needsImage]), [['CAST-01', 2, false], ['CAST-02', 0, true], ['SET-01', 2, false], ['PROP-01', 0, true]]);
  assert.deepEqual(worldCounts(items), {cast:2, sets:1, props:1});
  assert.deepEqual(worldFacets(items).map(facet => [facet.key, facet.count]), [['all', 4], ['CHARACTER', 2], ['SCENE', 1], ['PROP', 1], ['missing', 2]]);
  assert.equal(worldItems([], []).length, 0);
});

test('the wall keeps every type under All, one type under a type filter, and only what needs fixing under Needs an image', () => {
  const items = worldItems(assets, shots);
  assert.deepEqual(worldGroups(items).map(g => [g.type, g.items.length]), [['CHARACTER', 2], ['SCENE', 1], ['PROP', 1]]);
  assert.deepEqual(worldGroups(items, 'SCENE').map(g => g.type), ['SCENE']);
  assert.deepEqual(worldGroups(items.filter(i => i.type !== 'PROP'), 'PROP').map(g => [g.type, g.items.length]), [['PROP', 0]], 'an empty type still shows, so there is somewhere to add');
  assert.deepEqual(worldGroups(items, 'missing').map(g => [g.type, g.items.map(i => i.assetCode)]), [['CHARACTER', ['CAST-02']], ['PROP', ['PROP-01']]]);
  assert.deepEqual(worldGroups(worldItems([], []), 'all').map(g => g.items.length), [0, 0, 0]);
});

test('the editor opens on the picked card while it is on the wall, and on nothing otherwise', () => {
  const items = worldItems(assets, shots);
  assert.equal(activeItem(worldGroups(items), 'as_SET-01').assetCode, 'SET-01');
  assert.equal(activeItem(worldGroups(items), ''), null, 'nothing opens by itself');
  assert.equal(activeItem(worldGroups(items, 'SCENE'), 'as_CAST-02'), null, 'a card the filter hides is not open');
  assert.equal(activeItem(worldGroups([], 'all'), 'x'), null);
});

test('the view, the card in front of you and the scene filter survive a trip to the sheet, per episode, and storage failures start at the script', () => {
  const store = new Map();
  globalThis.sessionStorage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value)};
  try {
    assert.deepEqual(restoredWorld('ep_a'), {view:'script', pick:'', scene:null});
    rememberWorld('ep_a', {view:'world', pick:'as_CAST-02', scene:'sc2', extra:'ignored'});
    assert.deepEqual(restoredWorld('ep_a'), {view:'world', pick:'as_CAST-02', scene:'sc2'});
    rememberWorld('ep_a', {view:'world', pick:'as_CAST-02'});
    assert.deepEqual(restoredWorld('ep_a'), {view:'world', pick:'as_CAST-02', scene:null}, 'no scene chosen is everything');
    assert.deepEqual(restoredWorld('ep_b'), {view:'script', pick:'', scene:null});
    store.set('zf.world:ep_c', '{"view":"elsewhere","pick":7,"scene":3}');
    assert.deepEqual(restoredWorld('ep_c'), {view:'script', pick:'', scene:null});
    store.set('zf.world:ep_d', 'not json');
    assert.deepEqual(restoredWorld('ep_d'), {view:'script', pick:'', scene:null});
    globalThis.sessionStorage = {getItem() {throw new Error('blocked');}, setItem() {throw new Error('blocked');}};
    assert.deepEqual(restoredWorld('ep_a'), {view:'script', pick:'', scene:null});
    assert.doesNotThrow(() => rememberWorld('ep_a', {view:'world', pick:''}));
  } finally {delete globalThis.sessionStorage;}
});

test('the scene filter keeps one scene\'s assets, never loses an asset no shot places, and stacks with the type and needs-image filters', () => {
  const items = worldItems(assets, [...shots, shot('S04', ['PROP-01'], undefined)]);
  assert.equal(sceneFilter(items, null), items, 'everything is the default');
  assert.deepEqual(sceneFilter(items, 'sc1').map(item => item.assetCode), ['CAST-01', 'SET-01']);
  assert.deepEqual(sceneFilter(items, 'sc2').map(item => item.assetCode), ['SET-01']);
  assert.deepEqual(sceneFilter(items, 'sc9'), [], 'a scene nothing uses shows nothing');
  assert.deepEqual(sceneFilter(items, UNSCENED).map(item => item.assetCode), ['CAST-02', 'PROP-01'], 'an asset with no scene (nobody uses it, or only a scene-less shot) is under Unscened');
  assert.deepEqual(worldGroups(sceneFilter(items, UNSCENED), 'missing').map(group => [group.type, group.items.map(item => item.assetCode)]), [['CHARACTER', ['CAST-02']], ['PROP', ['PROP-01']]]);
  assert.deepEqual(worldFacets(sceneFilter(items, 'sc1')).map(facet => [facet.key, facet.count]), [['all', 2], ['CHARACTER', 1], ['SCENE', 1], ['PROP', 0], ['missing', 0]], 'counts follow the filter');
  assert.deepEqual(sceneFilter([], 'sc1'), []);
});
