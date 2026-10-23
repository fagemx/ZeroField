export const JOURNAL_CAP = 20 * 1024 * 1024;
const STORE = 'drafts', SIZES = 'sizes';
export function journalScope({origin = globalThis.location?.origin || '',slug,actorId,epId,resourceKind,resourceId}) {
  if (![slug,actorId,epId,resourceKind,resourceId].every(Boolean)) throw new TypeError('Complete journal identity required');
  return JSON.stringify([origin,slug,actorId,epId,resourceKind,resourceId]);
}
export const journalKey = (scope,tabId) => JSON.stringify([scope,tabId]);
export function createWritingJournal({indexedDB = globalThis.indexedDB,cap = JOURNAL_CAP} = {}) {
  let opening;
  const open = () => opening ||= new Promise((resolve,reject)=>{
    if (!indexedDB) { reject(new Error('IndexedDB is unavailable')); return; }
    const request = indexedDB.open('zerofield-writing-recovery',2);
    request.onupgradeneeded = () => {
      const store=request.result.objectStoreNames.contains(STORE)?request.transaction.objectStore(STORE):request.result.createObjectStore(STORE,{keyPath:'key'});
      if(!store.indexNames.contains('scope'))store.createIndex('scope','scope');
      if(!request.result.objectStoreNames.contains(SIZES)){
        const sizes=request.result.createObjectStore(SIZES,{keyPath:'key'});
        // Metadata-only capacity accounting after a one-time format upgrade.
        const cursor=store.openCursor();cursor.onsuccess=()=>{const row=cursor.result;if(row){sizes.put({key:row.key,bytes:new TextEncoder().encode(JSON.stringify(row.value)).byteLength});row.continue();}};
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => { opening = null; reject(request.error); };
    request.onblocked = () => { opening = null; reject(new Error('Recovery database is blocked')); };
  });
  async function transaction(mode, work) {
    const db = await open();
    return new Promise((resolve,reject)=>{
      const tx = db.transaction([STORE,SIZES],mode), store = tx.objectStore(STORE),sizes=tx.objectStore(SIZES);
      let result, problem;
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(problem || tx.error || new Error('Recovery transaction failed'));
      work(store,sizes,value=>{result=value;},error=>{problem=error;tx.abort();});
    });
  }
  return {
    list: scope => transaction('readonly',(store,_sizes,done)=>{
      // Never materialize another actor/episode/resource's private text.
      const request = store.index('scope').getAll(scope);
      request.onsuccess = () => done(request.result);
    }),
    put: (key, value) => transaction('readwrite',(store,sizes,done,fail)=>{
      const entry = {...value,key};
      const bytes = new TextEncoder().encode(JSON.stringify(entry)).byteLength;
      // The shared transaction serializes capacity accounting across browser tabs.
      const request = sizes.getAll();
      request.onsuccess = () => {
        const used = request.result.filter(item=>item.key!==key).reduce((total,item)=>total+item.bytes,0);
        if (used+bytes>cap) { fail(new Error('Recovery storage capacity exceeded')); return; }
        store.put(entry);sizes.put({key,bytes});done(true);
      };
    }),
    remove: (key, throughSequence = Infinity) => transaction('readwrite',(store,sizes,done)=>{
      const request = store.get(key);
      request.onsuccess = () => { if (request.result && request.result.localSequence<=throughSequence){store.delete(key);sizes.delete(key);}done(true); };
    }),
  };
}
