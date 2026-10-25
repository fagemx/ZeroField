// Authentication, envelopes and replay remain owned by storyRequest.
export function createWritingTransport(epId, request) {
  if (!epId || typeof request !== 'function') throw new TypeError('Episode and request are required');
  const base = `/episodes/${encodeURIComponent(epId)}/writing/`;
  return (tail, method = 'GET', body, options = {}) => {
    if (typeof tail !== 'string' || tail.startsWith('/') || tail.includes('..')) throw new TypeError('Relative writing route required');
    return request(base + tail, method, body, options);
  };
}
// A session owns every request and late response. Disposal never flushes private data.
export function createActorBoundRequest(actorId, request, onIdentityLost = () => {}) {
  if (!actorId) throw new TypeError('Actor is required');
  let active = true;
  const controllers = new Set();
  const disposed = () => new DOMException('Writing session disposed', 'AbortError');
  const bound = async (path, method = 'GET', body, options = {}) => {
    if (!active) throw disposed();
    const controller = new AbortController(), abort = () => controller.abort();
    controllers.add(controller);
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener('abort', abort, {once:true});
    try {
      const result = await request(path, method, body, {...options, expectedActorId:actorId, signal:controller.signal});
      if (!active || controller.signal.aborted) throw disposed();
      return result;
    } catch (error) {
      if (active && [401,403].includes(error.status)) {bound.dispose();onIdentityLost();}
      throw error;
    } finally {
      controllers.delete(controller);options.signal?.removeEventListener('abort', abort);
    }
  };
  bound.dispose = () => {active = false;for (const controller of controllers) controller.abort();controllers.clear();};
  return bound;
}
export const mutationId = () => crypto.randomUUID();
export function writingAction(transport, tail, body, options = {}) {
  // The closure is the retry handle: never replace its key on retry.
  const idempotencyKey = options.idempotencyKey || mutationId();
  return () => transport(tail, 'POST', body, {...options, idempotencyKey});
}
