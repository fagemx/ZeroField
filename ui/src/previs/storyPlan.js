import { ACTIONS, DURATIONS, FACINGS, LENSES, MOVES, SETS, defaultPlan, planFromSlate } from './plan.js';

// Storyboard metadata seeds a new shot. A director's draft or rendered plan always wins.
export function resolveShotPlan(shot, { draft, stored, rendered } = {}) {
  const saved = draft || stored || rendered;
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
