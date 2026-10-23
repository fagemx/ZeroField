// Authentication, envelopes and replay remain owned by storyRequest.
export function createWritingTransport(epId, request) {
  if (!epId || typeof request !== 'function') throw new TypeError('Episode and request are required');
  const base = `/episodes/${encodeURIComponent(epId)}/writing/`;
  return (tail, method = 'GET', body, options = {}) => {
    if (typeof tail !== 'string' || tail.startsWith('/') || tail.includes('..')) throw new TypeError('Relative writing route required');
    return request(base + tail, method, body, options);
  };
}
export const mutationId = () => crypto.randomUUID();
export function writingAction(transport, tail, body, options = {}) {
  // The closure is the retry handle: never replace its key on retry.
  const idempotencyKey = options.idempotencyKey || mutationId();
  return () => transport(tail, 'POST', body, {...options, idempotencyKey});
}
