// Performance layer (SPEC_10): what the actor does in a shot. Levels (scale, body, colour, focus, note, fit) shape the
// performance; one timeline of performance keys drives both the previs mannequin and the timed beat sheet written into
// the LTX Action & Audio Prompt. Ported from the shot-idiom generator's 表演調節 / perf_check; plain data, no DOM.

import { sampleActs } from '../../src/previs/plan.js';

/* ---------- levels: each one is a fixed instruction sentence the writer must follow ---------- */
export const SCALES = ['subtle', 'natural', 'open', 'heightened'];
export const SCALE_LABEL = { subtle: 'Subtle', natural: 'Natural', open: 'Open', heightened: 'Heightened' };
export const SCALE_TEXT = {
  subtle: 'Scale: subtle. The feeling stays in the eyes, the breath and the smallest changes of expression; the body hardly moves.',
  natural: 'Scale: natural. A real person\'s reaction: the expression reads clearly, with small gestures and business.',
  open: 'Scale: open. Expression, gesture and voice are clearly enlarged; tears fall, laughter is heard. Do not shrink it to a flicker: never use the words subtle, slightly, barely, faint or restrained.',
  heightened: 'Scale: heightened. Theatrical and unmistakable: the whole face and body carry the feeling, the voice rises and falls. Write at least one big visible action (he gasps, shouts, slams, staggers, recoils, sobs, laughs out loud) and never use the words subtle, slightly, barely, faint or restrained.',
};
export const BODIES = ['face', 'upper', 'full'];
export const BODY_LABEL = { face: 'Face', upper: 'Upper body', full: 'Full body' };
export const BODY_TEXT = {
  face: 'Body: face only. The body stays where the blocking puts it; only the face, the neck and the hands the action needs move.',
  upper: 'Body: upper body. He may lean, turn his shoulders, shrug and gesture; he does not step, stand up or travel.',
  full: 'Body: full body. He may step, turn round, cross the room or drop to his knees; write where each move starts and where it stops.',
};
export const COLORS = {
  smile: { label: 'Smile', text: 'Colour: a hint of a smile under the feeling (the corners of the mouth, the eyes), wry or relieved as the moment wants.', words: ['smile', 'grin', 'smirk'] },
  tears: { label: 'Tears', text: 'Colour: tears close under the feeling (red-rimmed eyes, a tight throat); they need not fall.', words: ['tear', 'eyes glisten', 'throat tightens', 'blinks back', 'wet eyes'] },
  anger: { label: 'Anger', text: 'Colour: anger under the feeling (a set jaw, a hard look, clipped breath).', words: ['jaw', 'anger', 'angry', 'hard', 'clench', 'grit'] },
  fear: { label: 'Fear', text: 'Colour: fear under the feeling (shallow breath, a glance away, fingers tightening, a smaller voice).', words: ['fear', 'afraid', 'shallow', 'flinch', 'tremb', 'shak'] },
  defiance: { label: 'Defiance', text: 'Colour: defiance under the feeling (the chin comes up, the gaze holds, the voice steadies).', words: ['chin', 'defian', 'holds his gaze', 'steady', 'squares'] },
  tenderness: { label: 'Tenderness', text: 'Colour: tenderness under the feeling (the face softens, the touch is gentle, the voice drops).', words: ['soft', 'gentle', 'tender', 'warm'] },
};
export const FOCUS = { eyes: 'Eyes', hands: 'Hands', posture: 'Posture', voice: 'Voice' };
// Fit decides which render lane carries the performance (SPEC_10 §3.3).
export const FITS = {
  pose: { label: 'Follow the previs pose', lane: 'Motion pass: the grey previs drives the body', text: 'Fit: follow the previs. Keep the blocked pose and its timing; add the feeling, not new moves.' },
  blocking: { label: 'Blocking only', lane: 'Layout Render: the actor follows the previs at 0.35, the text carries the rest', text: 'Fit: blocking only. Keep where he stands, where he faces and the order of the action; the pose, expression and size of the moves follow this text.' },
  free: { label: 'Free', lane: 'First frame and text only: no previs pose', text: 'Fit: free. Keep the person and the place; design the moves yourself so the feeling shows in action. Keep the must-have image and the line.' },
};

/* ---------- performance declarations: the manner an idiom asks for ---------- */
const BY_EVENT = {
  establish: { way: 'arrival', scale: 'natural', range: ['subtle', 'open'], body: 'full' },
  turn: { way: 'an inner shift', scale: 'subtle', range: ['subtle', 'open'], body: 'face' },
  action: { way: 'a task with weight', scale: 'natural', range: ['subtle', 'open'], body: 'upper' },
  reveal: { way: 'discovery', scale: 'natural', range: ['subtle', 'heightened'], body: 'upper' },
  pressure: { way: 'held tension', scale: 'subtle', range: ['subtle', 'open'], body: 'face' },
  end: { way: 'a decision', scale: 'natural', range: ['subtle', 'open'], body: 'upper' },
};
const SHOWPIECE = { scale: 'open', range: ['natural', 'heightened'] };
export const perfOf = (idiom, event) => ({ ...BY_EVENT[event], ...(idiom?.drama ? SHOWPIECE : {}), ...(idiom?.perf || {}) });

/* ---------- performance keys: one timeline for the mannequin and the beat sheet ----------
   A key sets some channels at time `at` (0..1 of the shot): look (where he faces), hands, walk (metres back from his
   mark); a key with `text` starts a beat-sheet segment. Each channel eases between the keys that set it. */
export const LOOK = { console: 0, dial: -0.12, window: -0.6, glass: -1.75, beacon: 0.05, room: Math.PI };
export const LOOK_LABEL = { console: 'the console', dial: 'the dial', window: 'a glance at the window', glass: 'the side glass', beacon: 'the beacon outside', room: 'the room', partner: 'the other person' };
export const HANDS = { down: 0, reach: 1.16, dial: 1.16, record: 0.95, raise: 2.3 };
export const HANDS_LABEL = { down: 'at his sides', reach: 'reaching to the console', dial: 'on the dial', record: 'on the record key', raise: 'raising the recorder' };
export const BEAT_STORY = {
  S01: { sound: 'rain hammering on the glass, the hatch clanging shut behind him', core: ['console'], acts: [
    { at: 0, look: 'console', hands: 'down', walk: 2.2, text: 'Kael comes in out of the rain and crosses the dome toward the console, water running off his jacket.' },
    { at: 60 / 96, walk: 0, hands: 'down', text: 'He stops at his station, still catching his breath.' },
    { at: 82 / 96, hands: 'reach', text: 'He lays a hand on the cold brass edge of the console.' }] },
  S02: { sound: 'radio static under the rain', core: ['static'], acts: [
    { at: 0, look: 'console', hands: 'down', text: 'He stands at the console, listening to the static.' },
    { at: 0.55, text: 'He waits, unmoving, for anything under the hiss.' }] },
  S03: { sound: 'the click of the dial, a low radio tone', core: ['dial', 'beacon'], key: 'far beyond the rain-streaked glass a beacon blinks on', acts: [
    { at: 0, look: 'glass', hands: 'down', text: 'He stands turned to the rain-streaked glass, listening.' },
    { at: 22 / 96, hands: 'down', text: 'He turns from the glass toward the console.' },
    { at: 39 / 96, look: 'console' },
    { at: 44 / 96, hands: 'dial', text: 'His hand finds the large brass dial and turns it; far beyond the glass a beacon blinks on.' },
    { at: 0.75, look: 'beacon', text: 'He freezes, head turned to the light.' }] },
  S04: { sound: 'a mechanical clunk as the key goes down, the reels starting to turn', core: ['record key'], key: 'the record key goes down', acts: [
    { at: 0, look: 'glass', hands: 'down', text: 'He turns back from the glass.' },
    { at: 22 / 96, hands: 'down' },
    { at: 39 / 96, look: 'console' },
    { at: 44 / 96, hands: 'record', text: 'His finger finds the record key and presses it down; the reels begin to turn.' },
    { at: 0.8, text: 'He keeps his hand on the key, listening.' }] },
  S05: { sound: 'the beacon\'s low hum through the glass', core: ['beacon'], acts: [
    { at: 0, look: 'console', hands: 'down', text: 'He watches the beacon pulse beyond the glass.' },
    { at: 0.5, text: 'He weighs whether to answer; nothing moves but his breathing.' }] },
  S06: { sound: 'the rain easing, the hum of the open channel', core: ['recorder'], line: { who: 'Kael', text: 'This is Kael. I hear you.' }, acts: [
    { at: 0, look: 'room', hands: 'down', text: 'He turns to the room, the recorder on its strap.' },
    { at: 0.35, hands: 'raise', text: 'He raises the recorder to his mouth and decides to speak.' }] },
  // The two-hander (grammar.js RELIEF). pacts: the other person's keys; they look at the subject unless told otherwise.
  R01: { sound: 'rain on the glass, the hatch thudding shut', core: ['coat'], acts: [
    { at: 0, look: 'partner', hands: 'down', text: 'Mira comes in shaking the rain off her coat; Kael turns from the console to face her.' },
    { at: 0.5, text: 'They take each other in across the floor, neither speaking yet.' }] },
  R02: { sound: 'rain, the low hum of the receivers', core: [], line: { who: 'Mira', text: 'You heard it too?' }, acts: [
    { at: 0, look: 'partner', hands: 'down', text: 'Mira stops in front of him, studying his face.' },
    { at: 0.4, text: 'She asks it quietly, watching for his answer.' }] },
  R03: { sound: 'the recorded tone, thin through the small speaker', core: ['recorder'], acts: [
    { at: 0, look: 'partner', hands: 'down', text: 'He holds her look.' },
    { at: 0.3, hands: 'raise', text: 'He lifts the recorder between them and lets the tone play.' }] },
  R04: { sound: 'the tone fading into static', core: [], line: { who: 'Mira', text: 'Static plays tricks at night.' }, acts: [
    { at: 0, look: 'partner', hands: 'down', text: 'Mira listens, her face hardening.' },
    { at: 0.5, body: 'crossed', text: 'She folds her arms, not ready to believe him.' }] },
  R05: { sound: 'a low tone through the glass', core: ['beacon'], acts: [
    { at: 0, look: 'partner', hands: 'down', text: 'He shakes his head, about to answer her.' },
    { at: 0.45, look: 'beacon', text: 'Far beyond the glass the beacon blinks; he turns to it.' },
    { at: 0.7, body: 'lean', text: 'He leans toward the glass, head toward the light.' }],
    pacts: [{ at: 0, look: 'partner' }, { at: 0.55, look: 'beacon' }] },
  R06: { sound: 'the rain easing, the hum of the open channel', core: [], line: { who: 'Mira', text: 'Then answer it.' }, acts: [
    { at: 0, look: 'partner', hands: 'down', text: 'Mira looks from the light to him.' },
    { at: 0.4, text: 'She gives him the smallest nod, handing him the moment.' }],
    pacts: [{ at: 0, look: 'beacon' }, { at: 0.3, look: 'partner' }] },
};
export const POSE_LABEL = { stand: 'standing', lean: 'leaning in', recoil: 'recoiling', slump: 'slumped', lookup: 'looking up', lookdown: 'looking down',
  face: 'hands to his face', crossed: 'arms crossed', open: 'arms open', kneel: 'kneeling' };
// The keys as the 3D Stage plan stores them (plan.js sampleActs): look, hands and walk become yaw, reach and back.
// Times written as n / 96 match plan.js's 0..96 beat clock, so the default keys replay the 3D Stage actions exactly.
// "partner" looks from mark `from` to the other person's mark `to`.
export const toActs = (acts, from, to) => acts && acts.map(k => Object.fromEntries(Object.entries({ at: k.at,
  yaw: k.look === 'partner' ? (to ? Math.atan2(to[0] - from[0], to[1] - from[1]) : undefined) : LOOK[k.look], reach: HANDS[k.hands], back: k.walk, body: k.body })
  .filter(([, v]) => v != null)));
// {yaw, reach, back, pose} at shot time u (0..1), sampled exactly as the 3D Stage samples a plan.
export const samplePerf = (acts, u) => sampleActs(toActs(acts), u);
// Beat-sheet segments: one per key with text, from its time to the next text key (or the end of the shot).
// poses: the body poses the keys in a segment arrive at (each segment's own; the first also takes keys before its start).
export function segments(acts, seconds) {
  const keys = acts.filter(k => k.text != null).sort((a, b) => a.at - b.at);
  return keys.map((k, i) => { const end = keys[i + 1]?.at ?? 1;
    const poses = acts.filter(a => a.body && a.body !== 'stand' && (i ? a.at >= k.at : true) && a.at < end).sort((a, b) => a.at - b.at).map(a => a.body);
    return { t0: k.at * seconds, t1: end * seconds, text: k.text, at: k.at, poses }; });
}
// What each pose looks like in the body, in words LTX can play (the 4090 pose test, SPEC_10 §7.6: a timed sentence of
// body mechanics drives the movement; a pose in the previs alone, or an adjective, barely does). core: words the
// written segment must keep.
export const POSE_MECHANICS = {
  lean: { text: 'the body leans in from the hips, the head forward', core: ['lean', 'forward'] },
  recoil: { text: 'the head snaps back, both arms fly up in front of the chest, the upper body rocks back half a step', core: ['arm', 'back'] },
  slump: { text: 'the shoulders drop and the head sinks forward, the back rounding', core: ['shoulder', 'slump', 'sink'] },
  lookup: { text: 'the head tips back to look up', core: ['up', 'tips back', 'head back'] },
  lookdown: { text: 'the head drops to look down', core: ['down', 'drops'] },
  face: { text: 'both hands come up to cover the face', core: ['hand'] },
  crossed: { text: 'the arms fold across the chest', core: ['arm', 'fold'] },
  open: { text: 'both arms open wide to the sides', core: ['arm', 'open'] },
  kneel: { text: 'the body drops to one knee', core: ['knee', 'kneel'] },
};
const mechanics = poses => (poses || []).filter(p => POSE_MECHANICS[p]).map(p => POSE_MECHANICS[p].text);
const sentence = x => x[0].toUpperCase() + x.slice(1) + '.';

/* ---------- the levels a beat plays at ---------- */
// scale/body: the director's setting, else the idiom's own. Beyond: larger than the previs was blocked for, so a
// "follow the pose" fit relaxes to "blocking only" (the matte frees the actor) unless the director set the fit.
export function levels(perf = {}, decl) {
  const scale = SCALES.includes(perf.scale) ? perf.scale : decl.scale, body = BODIES.includes(perf.body) ? perf.body : decl.body;
  const beyond = SCALES.indexOf(scale) > SCALES.indexOf(decl.range[1]) || BODIES.indexOf(body) > BODIES.indexOf(decl.body);
  const fit = FITS[perf.fit] ? perf.fit : beyond ? 'blocking' : 'pose';
  return { scale, body, beyond, fit, fitAuto: !FITS[perf.fit] && beyond, color: COLORS[perf.color] ? perf.color : '', focus: (perf.focus || []).filter(f => FOCUS[f]), note: String(perf.note || '').trim().slice(0, 80) };
}
export function levelLines(L) {
  const out = [FITS[L.fit].text, SCALE_TEXT[L.scale], BODY_TEXT[L.body]];
  if (L.color) out.push(COLORS[L.color].text);
  if (L.focus.length) out.push(`Focus: the feeling is carried mostly by ${L.focus.map(f => FOCUS[f].toLowerCase()).join(' and ')}.`);
  if (L.note) out.push(`Director's note (comes first): "${L.note}"`);
  return out;
}
// A signature of everything a written performance depends on: change any of it and the text is out of date.
export const sigOf = (L, segs, camera) => JSON.stringify([L.scale, L.body, L.color, L.focus, L.note, L.fit, segs.map(s => [s.t0.toFixed(1), s.t1.toFixed(1)]), camera]);

/* ---------- the beat sheet ---------- */
const t = v => v.toFixed(1);
// The template sheet: the keys' own sentences, plus one line that states the levels (so the levels reach LTX even
// before anyone writes the performance).
// facing: each segment's facing from the previs ("seen from behind"...), written into its time stamp so LTX gets it
// whatever the text says (the 4090 test: a freed actor turns to show the face the text describes).
const stamp = (s, i, facing) => `${t(s.t0)}–${t(s.t1)}s${facing?.[i] ? `, ${facing[i]}` : ''}:`;
export function templateSheet(segs, L, story, facing) {
  const lines = segs.map((s, i) => `${stamp(s, i, facing)} ${s.text}${mechanics(s.poses).map(m => ' ' + sentence(m)).join('')}`);
  const how = [{ subtle: 'subtle, the feeling in his eyes and breath', natural: 'natural', open: 'open, clearly enlarged', heightened: 'heightened, the whole body carries it' }[L.scale],
    { face: 'face only', upper: 'upper body', full: 'full body' }[L.body], L.color ? COLORS[L.color].label.toLowerCase() + ' underneath' : '', L.note].filter(Boolean).join('; ');
  lines.push(`Performance: ${how}.`);
  return finish(lines, story);
}
export function writtenSheet(segs, texts, story, facing) { return finish(segs.map((s, i) => `${stamp(s, i, facing)} ${texts[i]}`), story); }
function finish(lines, story) {
  if (story?.line) lines.push(`${story.line.who} says: "${story.line.text}"`);
  if (story?.sound) lines.push(`Sound: ${story.sound}.`);
  return lines.join('\n');
}

/* ---------- checks (perf_check in English) ---------- */
// Only camera senses: "he tilts his head", "pulls back his hand" and "cranes his neck" are acting.
const CAM = /\b(camera|close-?ups?|push-in|pull-out|pan(?:s|ning)? (?:left|right|across|over|up|down)|tilt(?:s|ing)? (?:up|down) (?:to|from)|zoom(?:s|ing)?|dolly|crane (?:up|down|shot)|(?:wide|close|medium|tracking|establishing|reverse|over-the-shoulder) shots?|framing|(?:low|high|reverse|dutch) angle|lens|focus pull|cut(?:s)? to)\b/i;
const STYLE = /\b(cgi|3d|render(?:ed)?|photoreal\w*|unreal|ue5|cartoon|anime|illustration)\b/i;
const ONSCREEN = /\b(captions?|subtitles?|title card|on-screen text|text overlay|logo|watermark)\b/i;
const NEG = /\b(not|never|no|don't|doesn't|without|avoid|instead of)\b/i;
const RESTRAINT = /\b(subtle|subtly|slight(?:ly)?|barely|faint(?:ly)?|restrained|minimal|hint of|imperceptibl\w*|almost still)\b/i;
const BIG = /\b(gasps?|sobs?|shouts?|yells?|laughs?|slams?|staggers?|jolts?|recoils?|lunges?|trembl\w+|shak(?:es|ing)|wide-eyed|cries|crying|tears (?:fall|stream|run)|clutch\w*|reels?|spins?|whips?|snaps?|jerks?|lurches?|bursts?|throws?|flings?|gapes?|heaves?|bellows?|roars?)\b/i;
const STRONG = /\b(shouts?|yells?|sobs?|slams?|lunges?|staggers?|collapses?|laughs? out loud|screams?)\b/i;
const UPPER = /\b(leans?|shrugs?|turns? (?:his )?shoulders?|bows?)\b/i;
const FULL = /\b(steps?|walks?|crosses|stands? up|kneels?|runs? (?:to|toward|towards|across|away|off|out|back)|spins? round|paces?|stumbles?)\b/i;  // "a tremble runs through him" is not a run
const clauses = s => String(s || '').split(/[.;:!?\n]|,\s*(?:but|and then)\b/i).map(x => x.trim()).filter(Boolean);
const hits = (text, re) => clauses(text).filter(c => !NEG.test(c)).map(c => c.match(re)?.[0]).filter(Boolean);
const stem = w => w.toLowerCase().replace(/(ing|ed|es|s)$/, '');
// Issues per segment (index) plus beat-wide ones under -1. skeleton = the template keys' text (what the previs shows).
const FACE_DETAIL = /\b(eyes?|eyebrows?|brow|jaw|mouth|lips|teeth|cheeks?|nostrils?|smile|frown|tears?)\b/i;
const FACES_CAMERA = /\b(turns? (?:round |around )?to (?:face )?(?:the )?(?:camera|us|lens)|faces the (?:camera|lens)|looks? (?:straight )?(?:in|at) (?:the )?(?:camera|lens)|towards? the (?:camera|lens))\b/i;
export function checkPerformance(texts, { segs, L, story, line, facing }) {
  const byShot = {}, add = (i, m) => { (byShot[i] ||= []).push(m); };
  const skeleton = segs.map(s => s.text).join(' ').toLowerCase();
  texts.forEach((x, i) => {
    const a = String(x || '').trim(), dur = segs[i].t1 - segs[i].t0;
    if (!a) return add(i, 'empty');
    const cam = a.match(CAM); if (cam) add(i, `camera word "${cam[0]}" (the camera is written in Camera Motion)`);
    const sty = a.match(STYLE); if (sty) add(i, `style word "${sty[0]}"`);
    const scr = a.match(ONSCREEN); if (scr) add(i, `on-screen text "${scr[0]}"`);
    if (line && line.length > 10 && a.toLowerCase().includes(line.toLowerCase().slice(0, 18))) add(i, 'the line is written into the performance (it is added separately)');
    const words = a.split(/\s+/).length; if (words > Math.round(dur * 22 + 14)) add(i, `${words} words for ${dur.toFixed(1)} s (about ${Math.round(dur * 22 + 14)} at most)`);
    for (const c of clauses(a)) if (NEG.test(c)) { const after = c.slice(c.search(NEG)); const bad = (story?.core || []).find(w => after.toLowerCase().includes(w.toLowerCase())); if (bad) add(i, `contradicts the action: "${bad}" is in a negated clause`); }
  });
  const all = texts.join(' ');
  for (const w of story?.core || []) if (!all.toLowerCase().includes(stem(w))) add(-1, `the action skeleton is missing "${w}"`);
  texts.forEach((x, i) => { for (const p of segs[i]?.poses || []) { const m = POSE_MECHANICS[p]; if (m && !m.core.some(w => String(x).toLowerCase().includes(w))) add(i, `the blocked ${p} is not written as body mechanics (${m.text})`); } });
  texts.forEach((x, i) => {
    if (!/from behind/.test(facing?.[i] || '')) return;
    if (FACES_CAMERA.test(x)) add(i, 'turns to face the camera, but this segment is seen from behind');
    const f = x.match(FACE_DETAIL); if (f) add(i, `describes his ${f[1].toLowerCase()}, which cannot be seen from behind (the model turns him round to show it)`);
  });
  if (story?.key) { const keyWords = story.key.toLowerCase().split(/\W+/).filter(w => w.length > 4); if (keyWords.length && !keyWords.some(w => all.toLowerCase().includes(w))) add(-1, `the must-have image is missing: ${story.key}`); }
  if (L.scale === 'open' || L.scale === 'heightened') { const r = hits(all, RESTRAINT); if (r.length) add(-1, `scale is ${L.scale} but it is written small: ${[...new Set(r)].join(', ')}`); }
  if (L.scale === 'heightened' && !hits(all, BIG).length) add(-1, 'scale is heightened but nothing big is written');
  if (L.scale === 'subtle') { const r = hits(all, STRONG); if (r.length) add(-1, `scale is subtle but it has: ${[...new Set(r)].join(', ')}`); }
  const allowed = re => hits(all, re).filter(w => !skeleton.includes(w.toLowerCase()));
  if (L.body === 'face') { const r = [...allowed(UPPER), ...allowed(FULL)]; if (r.length) add(-1, `body is face only but it has: ${[...new Set(r)].join(', ')}`); }
  if (L.body === 'upper') { const r = allowed(FULL); if (r.length) add(-1, `body is upper body but it has: ${[...new Set(r)].join(', ')}`); }
  // Seen from behind the whole beat, the colour lives in the posture: its face words would turn him round.
  const behind = facing?.length && facing.every(f => /from behind/.test(f));
  if (L.color && !behind && !COLORS[L.color].words.some(w => all.toLowerCase().includes(w))) add(-1, `colour is ${COLORS[L.color].label.toLowerCase()} but none of it is written (${COLORS[L.color].words.join(', ')})`);
  return { byShot, ok: !Object.keys(byShot).length };
}

/* ---------- the writer's brief (an open-weights model on the local machine) ---------- */
export const RULES = `You are the acting coach for a short live-action film rendered by a video model (LTX-2.5).
Where you sit: the scene is already planned shot by shot. Each shot has a camera (already written separately), a length, and timed segments that the 3D previs blocks out. You write only what the actor does in each segment: the behaviour, how the feeling changes, and how a line is said. The video model only plays concrete, visible behaviour; it cannot act out adjectives, and it acts badly when the text fights the blocking.

Rules:
1. Write the change and its rhythm, not a list of adjectives: where he starts, how it changes, how far, where it stops. Use visible parts of the body at the size the scale asks for.
2. Give the subtext in one short "as if ..." so the model knows why.
3. Say what not to play and what to play instead: at subtle and natural scale guard against overplaying; at open and heightened guard against underplaying.
4. Write only what is visible in the frame (each shot says what the framing shows).
5. Never describe the camera, framing or lens, and never use the words camera, close-up, push in, pan, zoom, shot, frame, angle or lens.
6. If the shot has a line, write how it is said (voice, volume, pace, pauses, how much the mouth moves) but not the line itself. Only the speaker's mouth moves.
7. Put the must-have image into its segment and say what it means.
8. No on-screen text, captions, titles or logos; no style words (realistic, 3D, CGI, render).
9. Keep each segment to about 20 words per second of the segment.
10. Plain present tense, short concrete sentences, like a director talking to an actor on set.
11. Keep the action skeleton (the blocked action of each segment): play it bigger or smaller, never replace it or write its opposite.
    Where a segment gives a body pose, write its mechanics: which part of the body moves, where to and how fast. Concrete limb movement at a time is what the video model plays; adjectives are not.
    Keep each segment's facing: when a segment is seen from behind, he never turns round to face us, and write nothing of his face (eyes, mouth, jaw): it cannot be seen, and naming it makes the model turn him round. Put the feeling into his posture, shoulders, head and hands.
12. The levels the director set for the shot come first; when they conflict with these rules, follow the levels, but never break rules 5 and 8, the line or the must-have image.`;
export function writerPrompt(scene, beats, versions = 0, repair = null) {
  const block = b => [
    `Shot ${b.id} "${b.title}" (${b.seconds} s). Camera, already decided: ${b.camera}. In frame: ${b.visible}.`,
    `  Levels (follow them):\n${b.levelLines.map(l => '    - ' + l).join('\n')}`,
    `  Segments to write (keep the times, the blocked action and the facing of each):\n${b.segs.map((s, i) => `    ${i + 1}. ${s.t0.toFixed(1)}–${s.t1.toFixed(1)}s, blocked action: ${s.text}${mechanics(s.poses).length ? ` Body (play it, in these mechanics): ${mechanics(s.poses).join('; ')}.` : ''}${b.facing?.[i] ? ` Facing: ${b.facing[i]}.` : ''}`).join('\n')}`,
    b.story.line ? `  Line: ${b.story.line.who} says "${b.story.line.text}" (write how it is said, not the words).` : '',
    b.story.key ? `  Must-have image: ${b.story.key}.` : '',
    repair?.[b.id] ? `  Your last attempt failed these checks, fix them: ${repair[b.id].join('; ')}` : ''].filter(Boolean).join('\n');
  const shape = versions
    ? `Write ${versions} different versions of shot ${beats[0].id}, each with a different reading (where the turn comes, which small action carries it, the subtext). Reply with JSON only: {"versions": [{"label": "the reading in at most six words", "segments": ["...", "..."]}]}`
    : `Reply with JSON only: {"shots": [{"id": "${beats[0].id}", "segments": ["...", "..."]}${beats.length > 1 ? ', ...' : ''}]} with one string per segment, in order.`;
  return `${scene.title}\n${scene.premise}\n\n${beats.map(block).join('\n\n')}\n\n${shape}`;
}
// The model's JSON, with any <think> block removed (thinking models put reasoning first).
export function parseWriter(answer) {
  const text = String(answer || '').replace(/<think>[\s\S]*?<\/think>/g, ''), m = text.match(/\{[\s\S]*\}/);
  try { return m ? JSON.parse(m[0]) : null; } catch { return null; }
}

/* ---------- what the framing shows (the writer only writes what is in frame) ---------- */
const VISIBLE = { EWS: 'his whole body, small in the dome', WS: 'his whole body and the console', MWS: 'him from the knees up', MS: 'him from the waist up',
  MCU: 'his head and shoulders', CU: 'his face', ECU: 'his eyes and brow', EYES: 'his eyes', INSERT: 'his hands on the console' };
export const visibleOf = s => (s.subj === 'prop' ? 'the console, with his hand when it reaches in' : s.end && s.end !== s.size ? `${VISIBLE[s.size]}, ending on ${VISIBLE[s.end]}` : VISIBLE[s.size]);

/* ---------- writing: write, check, rewrite the failures once; what still fails stays on the template ---------- */
export const issueList = chk => Object.entries(chk.byShot).flatMap(([i, ms]) => ms.map(m => (Number(i) < 0 ? m : `segment ${Number(i) + 1}: ${m}`)));
const checked = (b, got) => {
  const texts = Array.isArray(got) && got.length === b.segs.length ? got.map(x => String(x || '').trim()) : null;
  if (!texts) return { texts: null, issues: [`expected ${b.segs.length} segments`] };
  return { texts, issues: issueList(checkPerformance(texts, { segs: b.segs, L: b.L, story: b.story, line: b.story.line?.text, facing: b.facing })) };
};
// beats: [{id, title, seconds, camera, visible, levelLines, segs, story, L}]; ask(prompt) -> the model's answer.
// Returns {id: {texts, issues}}: issues empty = passed; texts null = nothing usable came back.
export async function writeScene(scene, beats, ask) {
  const out = {}; let todo = beats, repair = null;
  for (let round = 0; round < 2 && todo.length; round++) {
    const reply = parseWriter(await ask(writerPrompt(scene, todo, 0, repair)));
    repair = {};
    for (const b of todo) { out[b.id] = checked(b, reply?.shots?.find(x => x.id === b.id)?.segments); if (out[b.id].issues.length) repair[b.id] = out[b.id].issues; }
    todo = todo.filter(b => out[b.id].issues.length);
  }
  return out;
}
// Several readings of one beat, each checked; a version that fails is shown with its issues and cannot be applied.
export async function writeVersions(scene, b, ask, n = 3) {
  const reply = parseWriter(await ask(writerPrompt(scene, [b], n)));
  return (reply?.versions || []).slice(0, n).map(v => ({ label: String(v.label || '').slice(0, 60), ...checked(b, v.segments) })).filter(v => v.texts);
}
