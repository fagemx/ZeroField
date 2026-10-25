// The storyboard build's choices (SPEC_18 R7, R13). The estimate comes from the server (POST /episodes/{id}/storyboard-estimates); this
// file only reads it: which way of splitting lands nearest the length you have in mind, and what a build adds to the shots you have.
export const BREAKDOWN_MODES = ['auto', 'scene', 'cinematic'];
export const RATIOS = ['16:9', '9:16', '1:1', '21:9'];
export const TARGET_CHOICES = [45, 90];  // seconds; "not set" and "custom" sit beside them
export const TARGET_MIN = 10, TARGET_MAX = 1800;  // what the estimate endpoint accepts

// The target as the field holds it ('' while empty) to what the server takes (a whole number of seconds in range, else null).
export function targetSeconds(value) {
  const seconds = Math.trunc(Number(value));
  return Number.isFinite(seconds) && seconds >= TARGET_MIN && seconds <= TARGET_MAX ? seconds : null;
}

// The way of splitting whose planned length is nearest the target; the first of equals. null with no target or no estimate.
export function closestMode(modes, target) {
  if (!target || !modes) return null;
  let best = null;
  for (const [key, item] of Object.entries(modes)) {
    if (!item || !Number.isFinite(item.plannedSeconds)) continue;
    const gap = Math.abs(item.plannedSeconds - target);
    if (best === null || gap < best.gap) best = {key, gap};
  }
  return best?.key ?? null;
}

// The server answers {modes:[{breakdownMode, ...}]}; the dialog wants them by mode.
export const estimatesByMode = response => Object.fromEntries((response?.modes || []).map(item => [item.breakdownMode, item]));
