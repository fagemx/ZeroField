import { useEffect, useState, useSyncExternalStore } from 'react';
import { storyList, storyRequest } from '../storyModel.js';
import { cameraGroups, SHOT_LOOK_KINDS } from './lookModel.js';

// SPEC_19 4.3: the look catalog and the episode's settings, read once per page and shared by the shot composer and the Episode look
// page (R12). Screen state only; the server is the record.

// GET /catalog/looks?kind=<kind> (paged: storyList asks 100 at a time), one request per kind for the life of the page; a failure is
// tried again on the next mount.
const KINDS = {};
const readKind = kind => (KINDS[kind] ||= storyList('/catalog/looks?kind=' + kind).catch(error => {delete KINDS[kind]; throw error;}));

// The camera and move options (package B). preloaded ({camera, moves}): the options for the first paint (the tests).
const cameraState = ({camera, moves}) => ({status: 'ready', items: camera, moves, groups: cameraGroups(camera), error: ''});
export function useLookCatalog(preloaded = null) {
  const [state, setState] = useState(() => preloaded ? cameraState(preloaded) : {status: 'loading', items: [], moves: [], groups: cameraGroups([]), error: ''});
  useEffect(() => {
    if (preloaded) return undefined;
    let alive = true;
    Promise.all([readKind('camera'), readKind('move')]).then(([camera, moves]) => {if (alive) setState(cameraState({camera, moves}));},
      error => {if (alive) setState(old => ({...old, status: 'failed', error: error.message}));});
    return () => {alive = false;};
  }, []);
  return state;
}

// Film setup, palette and lighting (package C): {status, kinds: {genre: [...], era, tempo, palette, light}, error}. preloaded: the
// options by kind.
const optionsState = kinds => ({status: 'ready', kinds: Object.fromEntries(SHOT_LOOK_KINDS.map(kind => [kind, kinds?.[kind] || []])), error: ''});
export function useLookOptions(preloaded = null) {
  const [state, setState] = useState(() => preloaded ? optionsState(preloaded) : {...optionsState({}), status: 'loading'});
  useEffect(() => {
    if (preloaded) return undefined;
    let alive = true;
    Promise.all(SHOT_LOOK_KINDS.map(readKind)).then(lists => {if (alive) setState(optionsState(Object.fromEntries(SHOT_LOOK_KINDS.map((kind, index) => [kind, lists[index]]))));},
      error => {if (alive) setState(old => ({...old, status: 'failed', error: error.message}));});
    return () => {alive = false;};
  }, []);
  return state;
}

// ---- The episode's settings (GET /episodes/{id}/settings: {aspectRatio, stylePresetId, breakdownMode?, look?}), per episode. The
// Episode look page puts what its PUT answered here, so a shot composer on the page shows the new episode values at once (C1).
let settings = {};
const listeners = new Set();
const reading = new Map();
const keep = (epId, entry) => { settings = {...settings, [epId]: entry}; listeners.forEach(listener => listener()); };
export const episodeSettings = {
  get: epId => settings[epId] || null,
  subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  // Read (again) from the server; one request per episode at a time. request: storyRequest (a test passes a fake).
  load(epId, request = storyRequest) {
    if (!epId) return Promise.resolve(null);
    if (reading.has(epId)) return reading.get(epId);
    if (!settings[epId]) keep(epId, {status: 'loading', settings: null, error: ''});
    const read = request(`/episodes/${epId}/settings`).then(value => { keep(epId, {status: 'ready', settings: value || {}, error: ''}); return value || {}; },
      error => { keep(epId, {status: settings[epId]?.settings ? 'ready' : 'failed', settings: settings[epId]?.settings || null, error: error.message}); throw error; })
      .finally(() => reading.delete(epId));
    reading.set(epId, read);
    return read;
  },
  // What a PUT answered (the stored settings).
  put(epId, value) { if (epId) keep(epId, {status: 'ready', settings: value || {}, error: ''}); },
  clear() { settings = {}; reading.clear(); listeners.forEach(listener => listener()); },
};
const snapshot = () => settings;
// The episode's settings for a view: read once when first asked for; preloaded (an object) stands in for the server (the tests).
export function useEpisodeSettings(epId, preloaded = null) {
  const all = useSyncExternalStore(episodeSettings.subscribe, snapshot, snapshot);
  useEffect(() => { if (epId && !preloaded && !settings[epId]?.settings) episodeSettings.load(epId).catch(() => {}); }, [epId, preloaded]);
  if (preloaded) return {status: 'ready', settings: preloaded, error: ''};
  return all[epId] || {status: epId ? 'loading' : 'none', settings: null, error: ''};
}
