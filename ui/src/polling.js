import { useEffect, useRef } from 'react';

// Poll `load` every `delay` ms. A failed load never ends the loop: the next try waits longer (delay * 2^failures, at most
// maxDelay) and the first success goes back to `delay`. When the page becomes visible again (tab switch, laptop wake) or
// the browser comes back online, load runs at once, because background tabs throttle timers. The caller stops the loop
// by calling the returned function; the hook below does that when `delay` turns falsy. `env` is for tests.
export function startPolling(load, delay, {maxDelay = 30000, env = globalThis} = {}) {
  let stopped = false, failures = 0, running = false, timer = null;
  const doc = env.document;
  const arm = () => {
    if (stopped) return;
    env.clearTimeout(timer);
    timer = env.setTimeout(run, failures ? Math.min(maxDelay, delay * 2 ** failures) : delay);
  };
  async function run() {
    if (stopped || running) return;
    running = true; env.clearTimeout(timer);
    try { await load(); failures = 0; } catch { failures += 1; }
    running = false;
    arm();
  }
  const wake = () => { if (!doc || doc.visibilityState === 'visible') run(); };
  doc?.addEventListener?.('visibilitychange', wake);
  env.addEventListener?.('online', wake);
  arm();
  return () => {
    stopped = true; env.clearTimeout(timer);
    doc?.removeEventListener?.('visibilitychange', wake);
    env.removeEventListener?.('online', wake);
  };
}

// usePolling(load, delay): runs `load` every `delay` ms while delay is a positive number (null/0 = not polling).
// Change `delay` to change the pace; load may be a new function on every render.
export function usePolling(load, delay) {
  const latest = useRef(load);
  latest.current = load;
  useEffect(() => {
    if (!delay) return undefined;
    return startPolling(() => latest.current(), delay);
  }, [delay]);
}
