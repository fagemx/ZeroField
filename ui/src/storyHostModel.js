import { t } from './i18n/index.js';

// SPEC_16A 3.1: Story & World hosts the writing workspace in its script view. These two pure functions are the host's rules.

// The one primary button follows what you are looking at: the working script builds or updates the storyboard (through the dialog), a private
// idea or novel previews its adaptation, and a saved version or a private draft says what to do first. Nothing here sends a request.
export function primaryStoryAction({manuscript = 'working', writable = false, hasScript = false, hasShots = false, busy = false, loading = false, canAdapt = false} = {}) {
  const build = hasShots ? 'world.updateStoryboard' : 'story.confirmAndBuild';
  if (manuscript === 'source') return {action:'adapt', labelKey:'writing.authoring.previewAdaptation', disabled:!writable || busy || !canAdapt, hintKey:null};
  if (manuscript === 'working') return {action:'build', labelKey:build, disabled:!writable || busy || loading || !hasScript, hintKey:null};
  return {action:'none', labelKey:build, disabled:true, hintKey:manuscript === 'version' ? 'world.primaryHint_version' : 'world.primaryHint_branch'};
}

// What a production started from a story (SPEC_18 R16) hands to the workspace. A screenplay becomes the working script (the new production's
// own document: the host saves it before the workspace opens); an idea or a novel becomes the text of the private source of that name.
export function startHandOff(start) {
  if (!start || typeof start.text !== 'string' || !start.text.trim()) return {kind:'none'};
  return start.mode === 'script' ? {kind:'working', text:start.text} : {kind:'source', mode:start.mode, text:start.text};
}

// What the build dialog's confirm sends. The words you wrote are already saved by the workspace (the working script is the episode's own
// document, edited and locked by blocks), so this never sends the script itself: it makes sure the server has your text, then runs the
// same three requests as before. The server records the production baseline when the extraction is confirmed.
// flush: resolves true when the server holds what is on screen. wait: follows a task to its end. onDone: after the storyboard exists.
export async function buildStoryFromWorkspace({epId, breakdownMode = 'auto', settings, request, wait, flush, onDone}) {
  if (flush && !(await flush())) throw new Error(t('writing.authoring.serverSaveRequired'));
  await request(`/episodes/${epId}/settings`, 'PUT', {...settings, breakdownMode});
  await wait(await request(`/episodes/${epId}/asset-extractions`, 'POST'));
  const result = await wait(await request(`/episodes/${epId}/storyboards`, 'POST', {breakdownMode}));
  await onDone?.(result);
  return result;
}
