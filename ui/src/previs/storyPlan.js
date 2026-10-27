import { ACTIONS, DURATIONS, FACINGS, LENSES, MOVES, SETS, defaultPlan, describePlan, planFromSlate } from './plan.js';
import { placeOnStage } from './blocking.js';

// SPEC_20 R26: a shot's plan is stored in the project (GET/PUT /shots/{shotId}/previs-plan) with a revision every write names.
export const PLAN_CONFLICT = 'DRAMA_PREVIS_REVISION_CONFLICT';

// Where a shot's plan comes from, the first one found: the director's unsaved draft in this browser, the plan stored in the
// project, the plan a rendered previs carries in its WebM title (the backup from before plans were stored), the plan just
// rendered here before its file is read back, and last the storyboard's seed on top of what the slate text says.
export function resolveShotPlan(shot, { draft, stored, embedded, rendered } = {}) {
  const saved = draft || stored || embedded || rendered;
  if (saved) return { ...defaultPlan(), ...saved };
  const plan = planFromSlate(shot?.slate), generated = shot?.previsPlan;
  if (generated && typeof generated === 'object' && !Array.isArray(generated)) {
    for (const [key, values] of Object.entries({ set: SETS, lens: LENSES, move: MOVES, action: ACTIONS, facing: FACINGS, seconds: DURATIONS })) {
      if (values.includes(generated[key])) plan[key] = generated[key];
    }
  }
  if (plan.set === 'parallax' && shot?.setAsset?.url) plan.layers = [{ id: 'far', src: shot.setAsset.url }];
  return plan;
}

// Plans compare as data: key order (the database sorts keys) and undefined values (JSON drops them) do not count.
const sorted = value => (Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value);
const asData = value => JSON.stringify(sorted(JSON.parse(JSON.stringify(value ?? null))));
export const samePlan = (a, b) => asData(a) === asData(b);

// A draft kept in this browser: {plan, base}, base being the stored revision the edits started from. A draft written before
// plans were stored in the project is the bare plan, so it started from nothing stored (revision 0).
export function readDraft(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  if (!('plan' in value)) return { plan: value, base: 0 };
  const { plan, base } = value;
  return plan && typeof plan === 'object' && !Array.isArray(plan) && Number.isInteger(base) && base >= 0 ? { plan, base } : null;
}

// A shot can store its plan when it is a story shot (a row of the cinema or lab sheet, with a shot id and a revision).
export const storable = shot => Boolean(shot?.shotId) && Number.isInteger(shot?.previsRevision);
// The previs-plan route's answer as the stage holds it.
export const storedPlan = data => ({ plan: data?.plan ?? null, revision: data?.planRevision ?? 0, updatedAt: data?.updatedAt ?? null,
  updatedBy: data?.updatedBy ?? null, castOptions: Array.isArray(data?.castOptions) ? data.castOptions : [] });
// Shots whose stored plan the stage still has to read: a revision newer than the one it holds, every stored plan once, and the
// shot on stage once (the production's cast codes come with it).
export function plansToLoad(shots, held = {}, currentRid = null) {
  return shots.filter(shot => storable(shot) && (held[shot.rid] ? held[shot.rid].revision < shot.previsRevision : shot.previsStored || shot.rid === currentRid));
}

// request(path, method, body, options) is storyModel's storyRequest; a test passes a fake one.
export const loadPlan = async (request, shotId) => storedPlan(await request(`/shots/${shotId}/previs-plan`));
// Store plan over revision base. Resolves {ok: true, saved} or, when someone stored another revision since, {ok: false, conflict:
// {currentRevision, stored}}; other failures throw. A conflict whose stored plan already is this plan (a save retried after its
// answer was lost) is no conflict.
export async function savePlan(request, shotId, plan, base) {
  try {
    return { ok: true, saved: storedPlan(await request(`/shots/${shotId}/previs-plan`, 'PUT', { plan }, { headers: { 'If-Match': `"${base}"` } })) };
  } catch (error) {
    if (error?.code !== PLAN_CONFLICT) throw error;
    const stored = await loadPlan(request, shotId);
    return samePlan(stored.plan, plan) ? { ok: true, saved: stored } : { ok: false, conflict: { currentRevision: stored.revision, stored } };
  }
}

// SPEC_20 R29: the slate text a plan reads as. Camera Motion is describePlan; Optical Rig keeps its camera and takes the plan's
// lens in place of the first focal length it names (the one planFromSlate reads back), or gains one.
const FOCAL = /\d+(?:\.\d+)?\s*mm/i;
export function slateFromPlan(plan, slate = {}) {
  const rig = String(slate.rig || '').trim(), lens = `${plan.lens}mm`;
  return { opticalRig: FOCAL.test(rig) ? rig.replace(FOCAL, lens) : rig ? `${rig} / ${lens}` : lens, cameraMotion: describePlan(plan) };
}

// SPEC_20 R29: who stands on set carries a cast code from the production's cast sheet: plan.code is the plan's own actor,
// plan.cast[i].code everyone else. A code is on set once per shot.
export const codesOnSet = plan => [plan.code, ...(plan.cast || []).map(member => member.code)].filter(Boolean);
const withCode = (person, code) => {
  const { code: _old, ...rest } = person;
  return code ? { ...rest, code } : rest;
};
// who: 'actor' or a cast index; an empty code takes the code off.
export function setCastCode(plan, who, code) {
  if (who === 'actor') return withCode(plan, code);
  return plan.cast?.[who] ? { ...plan, cast: plan.cast.map((member, at) => (at === who ? withCode(member, code) : member)) } : plan;
}
// Someone from the cast sheet joins the shot, standing a step to the right of whoever joined last (drag them on the plan).
export function addCastMember(plan, code) {
  const cast = plan.cast || [], [x, z] = (cast.length ? cast[cast.length - 1].mark : plan.mark) || [0, 0];
  return { ...plan, cast: [...cast, { code, mark: placeOnStage([x + 1.2, z]) }] };
}
export const removeCastMember = (plan, index) => ({ ...plan, cast: (plan.cast || []).filter((_, at) => at !== index) });
