import { useSyncExternalStore } from 'react';

// SPEC_19 1.2 I / 3.3: the Shot Stage has one player. The shot composer's top half shows it; the shot's right column (ShotFilmPanel)
// only queues what to play there: a take row, "Play around", a take tried in the cut. While no composer is on the page (the overview,
// Review), the column draws the same player itself. Either way one queue, one <video> decoding at a time.
//
// Screen state only, never written anywhere: {playing: {queue, at, around, run} | null, measured: {url: seconds}, hosts}.
//   queue: playlist() items ({shotId, shotIndex, index, url, in, out, source, number?}); at: the item playing; around: "Play around"
//   started it; run: a new number for each play, so playing the same thing again starts it over (the <video> is keyed on it).
//   measured: file lengths the player read, for the progress bar's seconds. hosts: composers on the page that draw the player.
let state = {playing: null, measured: {}, hosts: 0};
const listeners = new Set();
const set = next => { state = {...state, ...next}; listeners.forEach(listener => listener()); };

export const shotMonitor = {
  get: () => state,
  subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  play(queue, around = false) {
    set({playing: Array.isArray(queue) && queue.length ? {queue, at: 0, around: Boolean(around), run: (state.playing?.run || 0) + 1} : null});
  },
  // The item ended: the next one in the queue, or nothing when it was the last.
  next() {
    const playing = state.playing;
    if (playing) set({playing: playing.at + 1 < playing.queue.length ? {...playing, at: playing.at + 1} : null});
  },
  stop() { if (state.playing) set({playing: null}); },
  measure(url, seconds) {
    if (url && Number.isFinite(seconds) && state.measured[url] !== seconds) set({measured: {...state.measured, [url]: seconds}});
  },
  // A composer draws the player while it is mounted; the returned function lets go.
  host() {
    set({hosts: state.hosts + 1});
    let held = true;
    return () => { if (held) { held = false; set({hosts: Math.max(0, state.hosts - 1)}); } };
  },
};

export const useShotMonitor = () => useSyncExternalStore(shotMonitor.subscribe, shotMonitor.get, shotMonitor.get);
// The item playing now, or null.
export const playingItem = playing => (playing ? playing.queue[playing.at] || null : null);
