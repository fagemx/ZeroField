// SPEC_19 package C: the film setup, palette and lighting options as GET /catalog/looks?kind=... answers them, built from
// docs/specs/SPEC_19_LOOK_OPTIONS_DRAFT.md (ids, order, main colour first) until project_docs/look_catalog.json carries them. labelKey
// follows the catalog's convention, lookCatalog.<kind>.<camelCaseId>; preview is null until the sample media are made (4.4).
const camel = id => id.replace(/-([a-z0-9])/g, (_, char) => char.toUpperCase());
const IDS = {
  genre: ['auto', 'rain-mystery', 'quiet-drama', 'creeping-unease', 'instrument-room-sf', 'distant-miles', 'field-record', 'bright-caper', 'close-warmth'],
  era: ['auto', 'early-lens', 'saturated-print', 'grain-film', 'tape-era', 'clean-digital'],
  tempo: ['auto', 'still-hold', 'slow-drift', 'hold-then-burst', 'staccato-run'],
  palette: ['auto', 'midnight-slate', 'lamp-amber', 'verdigris-rust', 'bone-ink', 'wet-glass-neon', 'moss-fog', 'sea-bleached', 'cinder-glow', 'floe-white',
    'mulberry-hour', 'sugar-paper', 'dry-ochre'],
  light: ['auto', 'window-side', 'practical-lamp', 'hard-top', 'backlight-rim', 'instrument-glow', 'overcast-flat', 'low-sun'],
};
export const HEX = {
  'midnight-slate': ['#2E3A4A', '#5B6F86', '#1B2330', '#8FA3B8', '#D8E0E8', '#C9953F'], 'lamp-amber': ['#C98A3D', '#8A4B2A', '#3B2A24', '#E8C48A', '#1E1A1A'],
  'verdigris-rust': ['#2F6B6B', '#B5602F', '#1C2B2E', '#D9A06A', '#6FA3A0'], 'bone-ink': ['#1A1A1A', '#E9E4D8', '#8C8780', '#4A4742', '#B8B3A8'],
  'wet-glass-neon': ['#101426', '#E0368B', '#28D3E6', '#5B3FA8', '#F2F2F7'], 'moss-fog': ['#6E7F63', '#3F4D3F', '#AEB8A5', '#D6DACD', '#232A24'],
  'sea-bleached': ['#D9D6CC', '#B7B2A5', '#8E9AA0', '#5E6A70', '#E8D9B5'], 'cinder-glow': ['#8E1F1F', '#3A0F10', '#D9593D', '#1A0C0C', '#F0B58A'],
  'floe-white': ['#BFD9E8', '#6FA3C7', '#2E5C85', '#F2F7FA', '#0F2A43'], 'mulberry-hour': ['#5A3E6B', '#2A1F3A', '#A78BB8', '#E6C9D9', '#F0A58A'],
  'sugar-paper': ['#F4B6C2', '#A8D8EA', '#FFE9A8', '#FFFFFF', '#7FB7A4'], 'dry-ochre': ['#C68E3F', '#8A5A2B', '#4A3020', '#E6D3A8', '#A86B3C'],
};
const option = (kind, id) => ({id, kind, labelKey: `lookCatalog.${kind}.${camel(id)}`, promptText: id === 'auto' ? '' : `${id.replace(/-/g, ' ')} as seen in the frame`,
  preview: null, ...(kind === 'palette' && id !== 'auto' ? {hex: HEX[id]} : {})});
export const LOOK_OPTIONS = Object.fromEntries(Object.entries(IDS).map(([kind, ids]) => [kind, ids.map(id => option(kind, id))]));
export const ALL_LOOK_OPTIONS = Object.values(LOOK_OPTIONS).flat();
