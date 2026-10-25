// SPEC_18 R9: appearance attributes picked as tags and composed into one description of the look. The attributes are not stored: the
// text is what the character is, so applying them only writes text, and a text someone already wrote is never overwritten unasked.
// The description is for the picture model, so it is composed in English whatever language the page is in; the labels are the page's.
export const GROUPS = [
  {key: 'basic', fields: ['gender', 'age', 'region', 'skin']},
  {key: 'face', fields: ['face', 'hairStyle', 'hairColor']},
  {key: 'body', fields: ['height', 'build']},
  {key: 'outfit', fields: ['top', 'bottom', 'shoes', 'accessory']},
];
export const TEXT_FIELDS = ['top', 'bottom', 'shoes', 'accessory'];
export const SWATCHES = {
  skin: {fair: '#F1D3B8', light: '#E3B48C', medium: '#C68E63', tan: '#A06A44', brown: '#7A4E31', deep: '#4A2E1F'},
  hairColor: {black: '#1E1A18', dark_brown: '#4A3326', brown: '#8B5A2B', blond: '#C9A66B', red: '#A5482B', gray: '#9A9AA2', white: '#E8E8EC'},
};
export const CHOICES = {
  gender: ['male', 'female', 'neutral'],
  age: ['child', 'teen', 'young', 'middle', 'elder'],
  region: ['east_asian', 'south_asian', 'southeast_asian', 'middle_eastern', 'african', 'european', 'nordic', 'latin_american'],
  skin: Object.keys(SWATCHES.skin),
  face: ['round', 'square', 'long', 'heart', 'oval'],
  hairStyle: ['short', 'long', 'braided', 'ponytail', 'curly', 'bald'],
  hairColor: Object.keys(SWATCHES.hairColor),
  height: ['short', 'average', 'tall'],
  build: ['lean', 'average', 'sturdy'],
};

const NOUN = {male: 'man', female: 'woman', neutral: 'androgynous person'};
const CHILD = {male: 'boy', female: 'girl'};
const AGE = {teen: 'teenage', young: 'young', middle: 'middle-aged', elder: 'elderly'};
const REGION = {east_asian: 'East Asian', south_asian: 'South Asian', southeast_asian: 'Southeast Asian', middle_eastern: 'Middle Eastern', african: 'African', european: 'European',
  nordic: 'Nordic', latin_american: 'Latin American'};
const SKIN = {fair: 'fair', light: 'light', medium: 'medium', tan: 'tan', brown: 'brown', deep: 'deep brown'};
const HAIR_COLOR = {black: 'black', dark_brown: 'dark brown', brown: 'brown', blond: 'blond', red: 'red', gray: 'gray', white: 'white'};
const FACE = {round: 'round', square: 'square', long: 'long', heart: 'heart-shaped', oval: 'oval'};
const HEIGHT = {short: 'short', average: 'average height', tall: 'tall'};
const BUILD = {lean: 'lean build', average: 'average build', sturdy: 'sturdy build'};

export const emptySelection = () => ({gender: '', age: '', region: '', skin: '', face: '', hairStyle: '', hairColor: '', height: '', build: '', top: '', bottom: '', shoes: '', accessory: ''});
export const hasSelection = selection => Object.values({...emptySelection(), ...selection}).some(value => String(value).trim());

// The same picks always give the same words, in the same order: who, skin, face, hair, body, then what they wear.
export function composeAppearance(selection = {}) {
  const pick = {...emptySelection(), ...selection}, parts = [];
  const noun = pick.age === 'child' ? CHILD[pick.gender] || 'child' : NOUN[pick.gender] || (pick.age || pick.region ? 'person' : '');
  const who = [AGE[pick.age], noun].filter(Boolean).join(' ');
  const region = REGION[pick.region] ? `${REGION[pick.region]} descent` : '';
  if (who) parts.push(who + (region ? ' of ' + region : ''));
  else if (region) parts.push('person of ' + region);
  if (SKIN[pick.skin]) parts.push(SKIN[pick.skin] + ' skin');
  if (FACE[pick.face]) parts.push(FACE[pick.face] + ' face');
  if (pick.hairStyle === 'bald') parts.push('bald');
  else if (pick.hairStyle || pick.hairColor) {
    const style = {short: 'short', long: 'long', braided: 'braided', curly: 'curly'}[pick.hairStyle] || '', color = HAIR_COLOR[pick.hairColor] || '';
    parts.push([style, color].filter(Boolean).join(' ') + ' hair' + (pick.hairStyle === 'ponytail' ? ' in a ponytail' : ''));
  }
  const body = [HEIGHT[pick.height], BUILD[pick.build]].filter(Boolean);
  if (body.length) parts.push(body.join(', '));
  const worn = TEXT_FIELDS.map(key => String(pick[key]).trim()).filter(Boolean);
  if (worn.length) parts.push('wearing ' + worn.join(', '));
  return parts.length ? parts.join(', ') + '.' : '';
}

// A text someone wrote is theirs: with any text there, the choice is theirs (replace or add after); with none, or the same text, there is none to make.
export const needsChoice = (current, composed) => Boolean(composed) && Boolean(String(current || '').trim()) && String(current).trim() !== composed;
export function mergeAppearance(current, composed, mode) {
  const text = String(current || '').trim();
  if (mode === 'replace' || !text) return composed;
  return text + (/[.!?。！？]$/.test(text) ? ' ' : '. ') + composed;
}
