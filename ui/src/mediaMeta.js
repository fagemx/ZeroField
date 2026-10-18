// Share both completed and in-flight metadata lookups across mounted media cells.
export const META_CACHE = new Map();
export function getMediaMeta(url, fetchMeta) {
  if (!META_CACHE.has(url)) {
    const request = Promise.resolve().then(() => fetchMeta(url + '/meta')).catch(error => { META_CACHE.delete(url); throw error; });
    META_CACHE.set(url, request);
  }
  return META_CACHE.get(url);
}
