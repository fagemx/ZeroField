// Cast & sets: a production's assets, the shots that use them and what they still lack, read as one wall.
export const WORLD_TYPES = ['CHARACTER', 'SCENE', 'PROP'];
export const FACETS = ['all', ...WORLD_TYPES, 'missing'];
export const KIND_FILTERS = {all: () => true, cast: asset => asset.type === 'CHARACTER', world: asset => asset.type !== 'CHARACTER'};
export const baseCode = code => String(code || '').split(':')[0].toUpperCase();
export const isWide = type => type !== 'CHARACTER';  // people are drawn portrait, sets and props landscape

const natural = text => String(text).split(/(\d+)/).map(part => /^\d+$/.test(part) ? part.padStart(6, '0') : part.toLowerCase()).join('');
export const bySlate = (a, b) => natural(a.shotIndex).localeCompare(natural(b.shotIndex));

// The shots that name an asset or one of its looks (CAST-01 or CAST-01:NIGHT) in slate order, and the scenes those shots sit in.
export function assetUses(asset, shots = []) {
  const code = baseCode(asset.assetCode);
  const used = shots.filter(shot => (shot.assets || []).some(ref => baseCode(ref) === code)).sort(bySlate);
  return {shots: used, sceneIds: [...new Set(used.map(shot => shot.sceneId).filter(Boolean))]};
}

export function worldItems(assets, shots = []) {
  return assets.map(asset => {
    const used = assetUses(asset, shots);
    return {...asset, uses: used.shots, sceneIds: used.sceneIds, needsImage: !asset.selectedImageUrl};
  });
}

export const worldCounts = items => ({cast: items.filter(item => item.type === 'CHARACTER').length, sets: items.filter(item => item.type === 'SCENE').length,
  props: items.filter(item => item.type === 'PROP').length});

export const worldFacets = items => FACETS.map(key => ({key, count: key === 'all' ? items.length
  : key === 'missing' ? items.filter(item => item.needsImage).length : items.filter(item => item.type === key).length}));

// The wall's sections. "All" keeps every type, even an empty one, so there is always somewhere to add; "missing" keeps only what has something to show.
export function worldGroups(items, facet = 'all') {
  const types = facet === 'all' || facet === 'missing' ? WORLD_TYPES : WORLD_TYPES.filter(type => type === facet);
  return types.map(type => ({type, items: items.filter(item => item.type === type && (facet !== 'missing' || item.needsImage))}))
    .filter(group => facet !== 'missing' || group.items.length);
}

// The card the inspector shows: the picked one while the filter still shows it, otherwise the first on the wall.
export function activeItem(groups, pick) {
  const shown = groups.flatMap(group => group.items);
  return shown.find(item => item.assetId === pick) || shown[0] || null;
}

// Which view the space was in, and the card in front of you, survive a trip to the sheet and back (this tab only).
const memory = epId => 'zf.world:' + epId;
export function restoredWorld(epId) {
  try {
    const saved = JSON.parse(globalThis.sessionStorage?.getItem(memory(epId)) || 'null');
    return {view: saved?.view === 'world' ? 'world' : 'script', pick: typeof saved?.pick === 'string' ? saved.pick : ''};
  } catch { return {view: 'script', pick: ''}; }
}
export function rememberWorld(epId, state) {
  try { globalThis.sessionStorage?.setItem(memory(epId), JSON.stringify({view: state.view, pick: state.pick})); } catch { /* No storage: the space opens on the script. */ }
}
