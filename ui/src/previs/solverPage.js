// The previs-solver page (SPEC_20 R27, R28): the 3D Stage's own plan code for a headless browser. The server
// (project_assistant/headless_previs.py) opens previs-solver.html with every request served from this build and
// everything else refused, then calls window.zfPrevis over the DevTools protocol:
//   solve(json)   -> JSON {ok: true, version, plan, warnings, base} | {ok: false, error: {code, path, message}}
//   render(json)  -> Promise of JSON {ok: true, dataUrl, width, height, frames} | {ok: false, error}   ({plan, title})
import { OPS_VERSION, solveRequest } from './ops.js';

const failure = error => ({ ok: false, error: { code: error?.code || 'PREVIS_SOLVER_FAILED', path: error?.path || null, message: String(error?.message || error) } });

window.zfPrevis = {
  version: OPS_VERSION,
  solve(json) {
    try { return JSON.stringify({ ok: true, ...solveRequest(JSON.parse(json)) }); } catch (error) { return JSON.stringify(failure(error)); }
  },
  async render(json) {
    try {
      const { plan, title } = JSON.parse(json), { contactSheet } = await import('./previsRender.js');
      return JSON.stringify({ ok: true, ...(await contactSheet(plan, { title })) });
    } catch (error) { return JSON.stringify(failure(error)); }
  },
};
window.zfPrevisReady = true;
