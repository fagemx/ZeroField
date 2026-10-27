import { normalizeStatus } from './format.js';
import { buildClips, planSeconds } from './timelineModel.js';

// SPEC_19 4.1: what a shot is doing in the film, derived from facts the page already holds, never written to the table.
// Pure functions: no DOM, no requests. A "shot" below is a shot view from GET /episodes/{id}/shots, in cinema slate order (the caller
// passes orderedShots(...), this module does not reorder), read through these fields:
//   shotId, rowId, shotIndex, reviewStatus (the table's status text), selectedVideoUrl, selectedImageUrl, previsVideoUrl,
//   previsPlan.seconds (planned length), trim {in, out|null} (already reset by the server when the take changed),
//   adoption {adopted, url, at, by} | null and takeSummary {total, newSinceAdoption} (SPEC_19 4.2).
// A caller may decorate a shot with two page-side facts: takes (mergeTakes() output, newest first) and inFlight (a task is running for
// this row). Without takes a shot is read through takeSummary, and without that through its selected video (one take, the one in the cell).

export const SHOT_STATES = ['blocked', 'generating', 'new_take', 'retake', 'adopted', 'empty'];
export const FILL_MODES = ['latest', 'previs', 'skip'];

const finite = value => typeof value === 'number' && Number.isFinite(value);
const urlOf = take => take?.url ?? take?.videoUrl ?? null;
// Milliseconds of an ISO string, a Date or an epoch number (seconds or milliseconds); NaN when there is no usable time.
function timeOf(value) {
  if (value === null || value === undefined || value === '') return NaN;
  if (value instanceof Date) return value.getTime();
  if (typeof value === 'number') return Number.isFinite(value) ? (Math.abs(value) < 1e11 ? value * 1000 : value) : NaN;
  return Date.parse(String(value));
}

// Which takes count as new for a shot. A shot is "anchored" when there is an adopted take to compare against: its status is Approved,
// or it is being re-shot (Retake) after an adoption was recorded. A take is new when it is newer than that adoption. A take without a
// time is older than every adoption (legacy candidates). An Approved shot with no adoption record was adopted at an unknown time: the
// take in the cell is the adopted one, and only a timed take newer than it (or any timed take, when the cell take is untimed) is new.
// A shot that is not anchored has nothing adopted, so every take is new.
function newness({status, adoption, takes}) {
  const value = normalizeStatus(status), recorded = Boolean(adoption && (adoption.at || adoption.url));
  if (!(value === 'Approved' || (value === 'Retake' && recorded))) return {anchored: false, isNew: () => true};
  const adoptedUrl = adoption?.url || null;
  let since = timeOf(adoption?.at);
  if (Number.isNaN(since)) {
    const inCell = takes.find(take => take?.selected), cellAt = inCell ? timeOf(inCell.createdAt) : NaN;
    since = Number.isNaN(cellAt) ? -Infinity : cellAt;
  }
  return {anchored: true, isNew: take => !(adoptedUrl ? urlOf(take) === adoptedUrl : take?.selected) && timeOf(take?.createdAt) > since};
}

// How many takes are newer than the adoption (or, for a shot with nothing adopted, how many takes it has). takes wins over takeSummary.
export function newTakeCount({status, adoption = null, takes = null, takeSummary = null}) {
  if (Array.isArray(takes)) return takes.filter(newness({status, adoption, takes}).isNew).length;
  if (takeSummary) return newness({status, adoption, takes: []}).anchored ? Number(takeSummary.newSinceAdoption) || 0 : Number(takeSummary.total) || 0;
  return 0;
}

// 'blocked' | 'generating' | 'new_take' | 'retake' | 'adopted' | 'empty', in that priority.
//   status: the table's status text (legacy Chinese values work). adoption: the shot view's adoption record or null.
//   takes: video takes ({url, createdAt?, selected?}), from mergeTakes() or GET /shots/{id}/videos. takeSummary: {total, newSinceAdoption},
//   used when takes is not loaded. inFlight: a story task or pipeline run is running for this row.
export function shotState({status, adoption = null, takes = null, inFlight = false, takeSummary = null}) {
  const value = normalizeStatus(status);
  if (value === 'Blocked') return 'blocked';
  if (inFlight) return 'generating';
  if (newTakeCount({status, adoption, takes, takeSummary}) > 0) return 'new_take';
  if (value === 'Retake') return 'retake';
  if (value === 'Approved') return 'adopted';
  return 'empty';
}

// What a shot view says about its takes, in the shape shotState() reads: its decorated takes, else its takeSummary, else the one video
// in its cell. extra: {takes, inFlight} override what the shot carries.
function factsOf(shot, extra = {}) {
  const takes = extra.takes ?? shot?.takes ?? null, takeSummary = shot?.takeSummary ?? null, loaded = Array.isArray(takes);
  return {status: shot?.reviewStatus ?? '', adoption: shot?.adoption ?? null,
    takes: loaded ? takes : takeSummary ? null : shot?.selectedVideoUrl ? [{url: shot.selectedVideoUrl, selected: true}] : [],
    takeSummary: loaded ? null : takeSummary, inFlight: Boolean(extra.inFlight ?? shot?.inFlight)};
}

// shotState() for a shot view (see the header).
export const shotStateOf = (shot, extra) => shotState(factsOf(shot, extra));
// The shot's new-take count for its badge, the same reading as shotStateOf().
export const newTakeCountOf = (shot, extra) => newTakeCount(factsOf(shot, extra));

// In the cut: the shot is adopted (status Approved, legacy value included) and there is a video in its cell for the film to use.
export const isAdopted = shot => normalizeStatus(shot?.reviewStatus) === 'Approved' && Boolean(shot?.selectedVideoUrl);
// The film's n in "Film n/m": shots in the cut. A trial take (playlist) never changes it.
export const adoptedCount = shots => (Array.isArray(shots) ? shots : []).filter(isAdopted).length;

// The video urls in a proposed cell text. Cells hold markdown links ("[Video](url)", "![alt](url)") or a bare url; a link is a video
// when it is labelled Video or ends in a video extension, and a project asset url with no extension is a video when its column is
// one of the shot's video outputs. An image is never a video take. (sheetModel.mediaOf is case sensitive and misses "[Video](...)".)
const LINK = /(!?)\[([^\]]*)\]\(([^)\s]+)\)/g;
function videoUrlsIn(text, column) {
  const value = String(text ?? '').trim(), found = [];
  const consider = (picture, label, url) => {
    if (!/^(https?:\/\/|\/(?!\/))/i.test(url)) return;
    const image = picture || /^image$/i.test(label) || /\.(png|jpe?g|gif|webp)(\?|$)/i.test(url);
    const plain = /\/assets\/pa_[0-9a-f]{32}$/.test(url) && /cinema|remaster|video|output/i.test(column);
    if (!image && (/^video$/i.test(label) || /\.(mp4|webm|mov|m4v)(\?|$)/i.test(url) || plain)) found.push(url);
  };
  for (const match of value.matchAll(LINK)) consider(Boolean(match[1]), match[2], match[3]);
  if (!found.length && !value.includes('](') && /^\S+$/.test(value)) consider(false, '', value);
  return found;
}

// The video urls a table_edit proposal entry would write: rowProposals() entries ({proposal, group, ...}) read through their changes,
// or an entry that already is {url, ...}. Only changes whose new value is a video count; an image change is not a video take.
function proposalVideos(entry) {
  if (!entry) return [];
  if (entry.url) return [entry.url];
  return (entry.group?.changes || entry.changes || []).flatMap(change => videoUrlsIn(change?.after, change?.column || ''));
}

// The video takes a rowProposals() entry would write ([] when it changes no video cell).
export const proposalTakeUrls = entry => proposalVideos(entry);
// A proposal entry that is nothing but a take: it edits one row only, and every change it makes is a video. Such an entry is reviewed
// in the Take list (its ✓ adopts it through POST /adoptions {proposalId}), not as a crew proposal. An entry that also changes text,
// or edits other rows (which the adoption endpoint refuses), stays a crew proposal.
export function takeOnlyProposal(entry) {
  const changes = entry?.group?.changes || [];
  return (entry?.size ?? 1) === 1 && changes.length > 0 && changes.every(change => videoUrlsIn(change?.after, change?.column || '').length > 0);
}
// Whether a merged take can be adopted from the Take list, and with which body for POST /shots/{id}/adoptions (null when it cannot).
// A take with a pending proposal behind it is always adopted through the proposal (SPEC_19 1.2 K), so the M8 gate decides it; a
// proposal that edits more rows than this one is applied as a crew proposal instead. Otherwise the candidate is adopted.
export function adoptionBody(take) {
  const entry = take?.entry, proposalId = entry?.proposal?.id ?? take?.proposalId ?? null;
  if (entry && (entry.size ?? 1) === 1 && proposalId !== null) return {proposalId};
  if (take?.videoId) return {videoId: take.videoId};
  return null;
}

// One list of takes for a shot, newest first: GET /shots/{id}/videos candidates ({videoId, url, selected, createdAt?}) and the pending
// media proposals for the row (rowProposals() entries), one per url (a candidate wins over a proposal with the same url). A take
// without a time is older than every timed one; among those the later one in the input is newer.
//   options: {status, adoption} of the shot, for the adopted and isNew marks (without them nothing is adopted and every take is new).
// Each take: {url, source: 'candidate'|'proposal', videoId, proposalId, entry, candidate, createdAt, time (ms | null), selected,
//   adopted (it is the take in the cut), isNew (newer than the adoption), number (1 = oldest)}. Adopt a candidate with its videoId and a
// proposal with its proposalId (entry carries the rowProposals() entry for applying it).
export function mergeTakes(candidates, proposals, options = {}) {
  const found = new Map();
  (Array.isArray(candidates) ? candidates : []).forEach(candidate => {
    const url = urlOf(candidate);
    if (url && !found.has(url)) found.set(url, {url, source: 'candidate', videoId: candidate.videoId ?? null, proposalId: null, entry: null, candidate, createdAt: candidate.createdAt ?? null, selected: Boolean(candidate.selected)});
  });
  (Array.isArray(proposals) ? proposals : []).forEach(entry => {
    for (const url of proposalVideos(entry)) {
      const seen = found.get(url);
      if (seen) { seen.entry = seen.entry || entry; continue; }
      found.set(url, {url, source: 'proposal', videoId: null, proposalId: entry.proposal?.id ?? entry.proposalId ?? null, entry, candidate: null,
        createdAt: entry.proposal?.created_at ?? entry.proposal?.createdAt ?? entry.createdAt ?? null, selected: false});
    }
  });
  const items = [...found.values()].map((take, order) => {
    const time = timeOf(take.createdAt);
    return {...take, time: Number.isNaN(time) ? null : time, order};
  });
  const approved = normalizeStatus(options.status) === 'Approved', adoptedUrl = options.adoption?.url || null;
  const {isNew} = newness({status: options.status, adoption: options.adoption || null, takes: items});
  items.sort((a, b) => {
    const left = a.time ?? -Infinity, right = b.time ?? -Infinity;
    return left === right ? b.order - a.order : left < right ? 1 : -1;
  });
  return items.map(({order, ...take}, position) => ({...take, number: items.length - position,
    adopted: approved && (adoptedUrl ? take.url === adoptedUrl : take.selected), isNew: isNew(take)}));
}

// The next shot after the current one that has a new take, wrapping from the end to the start; null when no other shot has one.
// Unknown or null currentShotId starts from the first shot.
export function nextNewTake(shots, currentShotId) {
  const list = Array.isArray(shots) ? shots : [], at = list.findIndex(shot => shot.shotId === currentShotId);
  for (let step = 1; step <= list.length; step += 1) {
    const shot = list[(at + step + list.length) % list.length];
    if (shot.shotId !== currentShotId && shotStateOf(shot) === 'new_take') return shot;
  }
  return null;
}

// The newest take of a shot: the first of its merged takes when it has them, else the video in its cell.
const latestUrl = shot => (Array.isArray(shot?.takes) ? urlOf(shot.takes[0]) : null) || shot?.selectedVideoUrl || null;

// Thumbnail source of a shot: its adopted take, else its newest take, else its previs, else none.
//   kind: 'adopted' | 'latest' | 'previs' | 'none'. videoUrl: the clip. posterUrl: the shot's key frame image to show instead of
//   decoding the clip (null for previs and none).
export function thumbOf(shot) {
  const poster = shot?.selectedImageUrl || null;
  if (isAdopted(shot)) return {kind: 'adopted', videoUrl: shot.selectedVideoUrl, posterUrl: poster};
  const latest = latestUrl(shot);
  if (latest) return {kind: 'latest', videoUrl: latest, posterUrl: poster};
  if (shot?.previsVideoUrl) return {kind: 'previs', videoUrl: shot.previsVideoUrl, posterUrl: null};
  return {kind: 'none', videoUrl: null, posterUrl: null};
}

// Seconds the shot occupies in the film: an adopted shot as trimmed (an untrimmed take is its measured length, or the planned seconds
// until its file is measured, as in the Timeline), any other shot its planned seconds.
function segmentOf(shot, index, measured) {
  const adopted = isAdopted(shot), clip = adopted ? buildClips([shot], {measured})[0] : null;
  return {shotId: shot.shotId, rowId: shot.rowId ?? null, shotIndex: shot.shotIndex, index, state: shotStateOf(shot), adopted,
    seconds: clip ? clip.length : planSeconds(shot), planned: !adopted, trimmed: Boolean(clip?.trimmed)};
}

// Previous, this and next shot of the film with what to show for each:
//   {index, total, prev, current, next}; each is null (no neighbour, or the shot is not in the list) or
//   {shotId, rowId, shotIndex, index, state, adopted, seconds, planned, trimmed, thumb (thumbOf)}.
//   options: {measured: {url: seconds}} file lengths read from the media, for exact seconds of untrimmed takes.
export function filmNeighbors(shots, shotId, {measured = {}} = {}) {
  const list = Array.isArray(shots) ? shots : [], at = list.findIndex(shot => shot.shotId === shotId);
  const entry = index => index < 0 || index >= list.length ? null : {...segmentOf(list[index], index, measured), thumb: thumbOf(list[index])};
  return {index: at, total: list.length, prev: at < 0 ? null : entry(at - 1), current: at < 0 ? null : entry(at), next: at < 0 ? null : entry(at + 1)};
}

// One segment per shot for the progress bar, width = seconds in the film. Each:
//   {shotId, rowId, shotIndex, index, state, adopted, seconds, planned (width is the plan, not a trimmed take), trimmed,
//    start, end (seconds into the film), share (seconds / film seconds, 0..1)}.
export function filmSegments(shots, {measured = {}} = {}) {
  const list = (Array.isArray(shots) ? shots : []).map((shot, index) => segmentOf(shot, index, measured));
  const total = list.reduce((sum, segment) => sum + segment.seconds, 0);
  let start = 0;
  return list.map(segment => {
    const placed = {...segment, start, end: start + segment.seconds, share: total > 0 ? segment.seconds / total : 1 / list.length};
    start = placed.end;
    return placed;
  });
}

// The line under the progress bar and the film window's title: {shots, adopted, withTake (not adopted but with a take), seconds}.
export function filmSummary(shots, {measured = {}} = {}) {
  const list = Array.isArray(shots) ? shots : [];
  const hasTake = shot => (Array.isArray(shot.takes) ? shot.takes.length : shot.takeSummary ? Number(shot.takeSummary.total) || 0 : shot.selectedVideoUrl ? 1 : 0) > 0;
  return {shots: list.length, adopted: adoptedCount(list), withTake: list.filter(shot => !isAdopted(shot) && hasTake(shot)).length,
    seconds: filmSegments(list, {measured}).reduce((sum, segment) => sum + segment.seconds, 0)};
}

// What the player plays, in film order, one item per playable shot: {shotId, shotIndex, index, url, in, out (null = to the end), source}.
//   source 'adopted': the adopted take, cut by its trim. Every other shot is filled by `fill`:
//   'latest' its newest take (source 'latest'), 'previs' its previs (source 'previs'), 'skip' nothing. A shot with nothing to play
//   for the chosen fill is left out. Whole clip: in 0, out null.
//   trial: {shotId, url}, a take being tried in place of that one shot (source 'trial', whole clip). It changes only that shot's item:
//   the shots, the counts and the other items are untouched, and nothing is written. Trying the shot's own adopted take keeps its trim.
export function playlist(shots, {fill = 'latest', trial = null} = {}) {
  const mode = FILL_MODES.includes(fill) ? fill : 'latest', items = [];
  (Array.isArray(shots) ? shots : []).forEach((shot, index) => {
    const base = {shotId: shot.shotId, shotIndex: shot.shotIndex, index}, adopted = isAdopted(shot);
    if (trial?.url && trial.shotId === shot.shotId && !(adopted && trial.url === shot.selectedVideoUrl)) {
      items.push({...base, url: trial.url, in: 0, out: null, source: 'trial'});
    } else if (adopted) {
      const from = finite(shot.trim?.in) && shot.trim.in > 0 ? shot.trim.in : 0, to = finite(shot.trim?.out) && shot.trim.out > from ? shot.trim.out : null;
      items.push({...base, url: shot.selectedVideoUrl, in: from, out: to, source: 'adopted'});
    } else {
      const url = mode === 'latest' ? latestUrl(shot) : mode === 'previs' ? shot.previsVideoUrl || null : null;
      if (url) items.push({...base, url, in: 0, out: null, source: mode});
    }
  });
  return items;
}

// ---------- SPEC_19 package D: references, seams, and adopting the newest takes of many shots ----------
// Additions only: nothing above reads them.

// R16: the references of a shot's adopted take whose upstream changed. takeRefs is the shot view's list (GET /episodes/{id}/shots or
// GET /shots/{id}): [{shotId, shotIndex, edge: 'start'|'end', takeUrl, at, use: 'first_frame'|'reference', stale, nowTakeUrl, frameUrl,
// adopted}], empty while nothing is adopted. The server decides stale; this only reads it.
export const staleTakeRefs = shot => (Array.isArray(shot?.takeRefs) ? shot.takeRefs : []).filter(ref => ref?.stale === true);

// What changed upstream of one stale reference, read with the quoted shot's current view (from the same shot list); null when the
// reference still resolves to the frame it quoted.
//   {kind: 'gone'}           the quoted shot has no take now (or is gone)
//   {kind: 'take', url}      the tag resolves to another take now (url: nowTakeUrl)
//   {kind: 'edge', seconds}  same take, the cut moved that edge: the new in point (0 untrimmed) or out point; null when the shot is not
//                            known here or its out point is the take's own end (its length is not known here)
export function takeRefChange(ref, shot = null) {
  if (!ref?.stale) return null;
  if (!ref.nowTakeUrl) return {kind: 'gone'};
  if (ref.nowTakeUrl !== ref.takeUrl) return {kind: 'take', url: ref.nowTakeUrl};
  const trim = shot?.trim || null;
  const seconds = !trim ? null : ref.edge === 'start' ? (finite(trim.in) && trim.in > 0 ? trim.in : 0) : finite(trim.out) ? trim.out : null;
  return {kind: 'edge', seconds};
}

// R17: the colour of a seam from its cut check (GET /episodes/{id}/cuts item, or null when the server lists no such pair):
// 'pass' (green, it holds), 'issue' (yellow, the check found problems), 'queued' (in the grader's queue), 'failed' (the check could not
// run) or 'none' (grey: never checked for these takes and points, or not checkable yet).
export const SEAM_STATES = ['pass', 'issue', 'queued', 'failed', 'none'];
export function seamState(cut) {
  const check = cut?.check;
  if (check?.state === 'done') return check.passed === true ? 'pass' : 'issue';
  return check?.state === 'queued' || check?.state === 'failed' ? check.state : 'none';
}

// The seams of the film: one between each two neighbouring shots of `shots` (film order, as the progress bar draws them), with the
// episode's cut for that pair matched on fromShotId and toShotId. A pair the server does not list (a lab clip sits between them in the
// server's film, or the cuts are not loaded) is an unchecked seam. Each:
//   {key ('fromShotId>toShotId'), index (of the shot before it), fromShotId, toShotId, fromShotIndex, toShotIndex,
//    state (seamState), checkable, blockedBy [{shotId, reason}], check (the cut's check or null), cut (the server's item or null)}
export function filmSeams(shots, cuts = []) {
  const list = Array.isArray(shots) ? shots : [];
  const byPair = new Map((Array.isArray(cuts) ? cuts : []).map(cut => [`${cut.fromShotId}>${cut.toShotId}`, cut]));
  return list.slice(1).map((after, at) => {
    const before = list[at], key = `${before.shotId}>${after.shotId}`, cut = byPair.get(key) || null;
    return {key, index: at, fromShotId: before.shotId, toShotId: after.shotId, fromShotIndex: before.shotIndex, toShotIndex: after.shotIndex,
      state: seamState(cut), checkable: Boolean(cut?.checkable), blockedBy: Array.isArray(cut?.blockedBy) ? cut.blockedBy : [], check: cut?.check || null, cut};
  });
}

// R18: what "Cuts only" plays, in film order: for each seam, the last `seconds` of the clip before it and the first `seconds` of the
// clip after it, so the whole episode's joins pass in a few seconds each, one clip at a time in the same player.
//   items: playlist() / filmPlayback() output (one clip per shot, already cut, filled and with any trial take). Two clips make a seam
//   only when their shots are neighbours in the film (index + 1): a shot left out leaves no seam across it.
//   Each result is its clip's item narrowed to the seam, plus seam {key, index, fromShotId, toShotId} and side 'out' | 'in'. When the
//   outgoing clip's end is not known (an untrimmed take whose file is not measured), its item has out null and tail: seconds, meaning
//   "start that many seconds before the end".
//   options: seconds (1), measured {url: file seconds}, only (a seam key: just that seam).
export function seamPlaylist(items, {seconds = 1, measured = {}, only = null} = {}) {
  const list = Array.isArray(items) ? items : [], span = finite(seconds) && seconds > 0 ? seconds : 1, result = [];
  list.forEach((before, at) => {
    const after = list[at + 1];
    if (!after || after.index !== before.index + 1) return;
    const seam = {key: `${before.shotId}>${after.shotId}`, index: before.index, fromShotId: before.shotId, toShotId: after.shotId};
    if (only && only !== seam.key) return;
    const from = finite(before.in) && before.in > 0 ? before.in : 0;
    const end = finite(before.out) ? before.out : finite(measured?.[before.url]) ? measured[before.url] : null;
    result.push(end === null ? {...before, in: from, out: null, tail: span, seam, side: 'out'}
      : {...before, in: Math.max(from, end - span), out: end, seam, side: 'out'});
    const start = finite(after.in) && after.in > 0 ? after.in : 0;
    result.push({...after, in: start, out: finite(after.out) ? Math.min(after.out, start + span) : start + span, seam, side: 'in'});
  });
  return result;
}

// §7 decision 6, the overview's "Adopt latest takes": what to do for one shot. takes: mergeTakes() output (newest first).
//   {body, take}  POST /shots/{id}/adoptions with body (adoptionBody(), as the shot column: through the proposal behind the take, else
//                 the candidate)
//   {skip}        'none' (no take yet), 'adopted' (the newest take is already in the cut), 'shared' (a pipeline proposal across several
//                 rows: apply it as a crew proposal), 'unavailable' (nothing to adopt it by)
export function adoptLatestPlan(takes) {
  const latest = Array.isArray(takes) && takes.length ? takes[0] : null;
  if (!latest) return {skip: 'none'};
  if (latest.adopted) return {skip: 'adopted', take: latest};
  const body = adoptionBody(latest);
  if (body) return {body, take: latest};
  return {skip: latest.entry && (latest.entry.size ?? 1) > 1 ? 'shared' : 'unavailable', take: latest};
}
