import {createWritingJournal, journalKey, journalScope} from './writingJournal.js';
import {actionId} from './writingToolsModel.js';

const copy = value => structuredClone(value);
const equal = (left,right) => JSON.stringify(left) === JSON.stringify(right);

// Narrative forms reuse the bounded authoring IDB journal, never a server/private-source store.
// Each mounted browser-tab instance has a unique key; recovery discovery is actor+episode scoped.
export class BibleFormRecovery {
  constructor({slug,actorId,epId,journal=createWritingJournal(),tabId=actionId(),notify=()=>{}}) {
    Object.assign(this,{slug,actorId,epId,journal,tabId,notify});
    this.indexScope=this.scope('bible_form_index','index');
    this.indexKey=journalKey(this.indexScope,tabId);
    this.sequence=0;this.durableSequence=-1;this.identitySequence=-1;
    this.dirty=false;this.state='recovery';this.recoveries=[];this.recoveryDecisions=new Map();this.work=Promise.resolve();
  }
  scope(resourceKind,resourceId) {return journalScope({slug:this.slug,actorId:this.actorId,epId:this.epId,resourceKind,resourceId});}
  snapshot() {return {state:this.state,dirty:this.isDirty(),recoverable:!this.localError&&(!this.dirty||this.durableSequence===this.sequence)&&(this.dirty||this.recoveries.length>0),
    localError:Boolean(this.localError),identityRequested:Boolean(this.identityRequested),identityPreserved:this.dirty&&this.identitySequence===this.sequence,
    preservedRecoveryKeys:this.recoveries.filter(row=>this.recoveryDecisions.get(row.key)===row.localSequence).map(row=>row.key),recoveries:this.recoveries,conflict:this.conflict,remote:this.remote};}
  emit() {this.notify(this.snapshot());}
  isDirty() {return this.dirty || this.recoveries.length>0;}
  recoveryState() {const {state,recoverable}=this.snapshot();return {state,recoverable};}
  open(base,draft) {
    if(this.dirty)return false;
    this.base=copy(base);this.draft=copy(draft);this.entityId=base?.bibleId || 'new';
    this.state=!this.discovered||this.recoveries.length?'recovery':'saved';this.conflict=false;this.remote=null;this.emit();return true;
  }
  async discover() {
    if(this.discovered)return;
    const indexes=await this.journal.list(this.indexScope);
    const recoveries=[],byEntity=new Map();
    for(const index of indexes){
      if(!Array.isArray(index.entities)||index.entities.length>1)continue;
      for(const entityId of index.entities){
        if(typeof entityId!=='string'||entityId.length>200)continue;
        if(!byEntity.has(entityId))byEntity.set(entityId,await this.journal.list(this.scope('bible_form',entityId)));
        const entries=byEntity.get(entityId);
        for(const entry of entries)if(entry.tabId===index.tabId&&entry.draft&&entry.entityId===entityId&&!recoveries.some(row=>row.key===entry.key))recoveries.push({...entry,indexKey:index.key});
      }
    }
    this.discovered=true;this.recoveries=recoveries;
    if(!this.dirty)this.state=recoveries.length?'recovery':'saved';this.localError=null;this.emit();
  }
  change(draft) {
    if(equal(draft,this.draft))return;
    this.draft=copy(draft);this.sequence++;this.dirty=true;this.identitySequence=-1;
    if(!this.conflict&&this.state!=='auth_lost')this.state='dirty';
    clearTimeout(this.timer);this.timer=setTimeout(()=>this.checkpoint(),250);
    this.maximum ||= setTimeout(()=>this.checkpoint(),1500);this.emit();
  }
  clearTimers(){clearTimeout(this.timer);clearTimeout(this.maximum);this.timer=null;this.maximum=null;}
  checkpoint() {
    this.clearTimers();
    if(!this.dirty)return Promise.resolve(!this.localError);
    const sequence=this.sequence,entityId=this.entityId,scope=this.scope('bible_form',entityId),key=journalKey(scope,this.tabId);
    const value={scope,tabId:this.tabId,entityId,base:copy(this.base),draft:copy(this.draft),localSequence:sequence,updatedAt:new Date().toISOString()};
    const index={scope:this.indexScope,tabId:this.tabId,entities:[entityId],localSequence:sequence,updatedAt:value.updatedAt};
    this.work=this.work.catch(()=>{}).then(async()=>{
      if(new TextEncoder().encode(JSON.stringify(value)).byteLength>2000000)throw new Error('Form recovery exceeds the bounded resource size');
      // Publish a content-free index first. A failed form write must never be called recoverable.
      await this.journal.put(this.indexKey,index);await this.journal.put(key,value);
      if(this.entityId===entityId&&this.sequence===sequence){
        this.durableSequence=sequence;this.localError=null;
        if(this.adopting){const row=this.adopting;if(row.key!==key)await this.removeEntry(row);this.recoveries=this.recoveries.filter(entry=>entry.key!==row.key);this.adopting=null;}
        if(!this.conflict&&this.state!=='auth_lost')this.state='local_only';
      }
      this.emit();return true;
    }).catch(error=>{this.localError=error;if(this.sequence===sequence&&!this.conflict&&this.state!=='auth_lost')this.state='save_failed';this.emit();return false;});
    return this.work;
  }
  async flush({reason='navigation',requireServer=false}={}) {
    if(!this.discovered)return false;
    if(!this.isDirty())return this.state!=='auth_lost'&&!this.localError;
    if(reason==='identity'){
      this.identityRequested=true;this.emit();
      if(!await this.refreshRecoveryRows())return false;
      return (!this.dirty||this.identitySequence===this.sequence)&&this.recoveries.every(row=>this.recoveryDecisions.get(row.key)===row.localSequence);
    }
    if(requireServer)return false; // This control never silently publishes an unrelated shared form.
    await this.checkpoint();
    return !this.recoveries.length&&!this.conflict&&this.state!=='auth_lost'&&this.durableSequence===this.sequence&&!this.localError;
  }
  async preserveIdentity() {
    if(!this.dirty)return false;
    const sequence=this.sequence;
    if(await this.checkpoint()&&this.sequence===sequence&&this.durableSequence===sequence){this.identitySequence=sequence;this.emit();return true;}
    return false;
  }
  async refreshRecoveryRows() {
    const fresh=[],scopes=new Map();let changed=false;
    try {
      for(const row of this.recoveries){
        if(!scopes.has(row.scope))scopes.set(row.scope,await this.journal.list(row.scope));
        const current=scopes.get(row.scope).find(entry=>entry.key===row.key);
        if(!current){this.recoveryDecisions.delete(row.key);changed=true;continue;}
        if(current.localSequence!==row.localSequence){this.recoveryDecisions.delete(row.key);changed=true;fresh.push({...current,indexKey:row.indexKey});}
        else fresh.push(row);
      }
      if(changed){this.recoveries=fresh;if(!this.dirty)this.state=fresh.length?'recovery':'saved';this.emit();}
      return true;
    } catch(error){this.discoveryError(error);return false;}
  }
  async preserveRecovery(row) {
    if(!await this.refreshRecoveryRows())return false;
    const current=this.recoveries.find(entry=>entry.key===row.key&&entry.localSequence===row.localSequence);
    if(!current)return false;
    this.recoveryDecisions.set(row.key,row.localSequence);this.emit();return true;
  }
  markError(kind) {
    if(!this.dirty)return;
    if(kind==='auth')this.state='auth_lost';
    if(this.state==='auth_lost'){this.emit();return;}
    if(kind==='conflict'||kind==='locked'){this.conflict=true;this.state='conflict';this.remote=null;}
    this.emit();
  }
  async removeEntry(row) {
    await this.journal.remove(row.key,row.localSequence);
    await this.journal.remove(row.indexKey,row.localSequence);
  }
  async restore(row,remote) {
    if(this.dirty||!this.recoveries.some(entry=>entry.key===row.key))return false;
    this.entityId=row.entityId;this.base=copy(row.base);this.draft=copy(row.draft);this.sequence++;this.dirty=true;this.identitySequence=-1;
    this.remote=copy(remote);this.conflict=Boolean(row.base?.version!==remote?.version);
    this.state=this.conflict?'conflict':'dirty';
    this.adopting=row;await this.checkpoint();this.emit();return true;
  }
  discoveryError(error){this.localError=error;this.state='save_failed';this.emit();}
  review(remote){this.remote=copy(remote);this.emit();}
  merged() {
    if(!this.conflict||!this.remote||this.state==='auth_lost')return false;
    this.base=copy(this.remote);this.conflict=false;this.remote=null;this.sequence++;this.identitySequence=-1;
    this.state='dirty';this.checkpoint();this.emit();return true;
  }
  async discardRecovery(row){await this.removeEntry(row);this.recoveryDecisions.delete(row.key);this.recoveries=this.recoveries.filter(entry=>entry.key!==row.key);if(!this.isDirty())this.state='saved';this.emit();}
  async discard(base,draft) {
    const sequence=this.sequence;this.clearTimers();await this.work;
    this.identitySequence=-1;this.durableSequence=-1;
    try {
      // Unlike a real server ACK, an explicit discard must not pretend failed IDB deletion succeeded.
      await this.journal.remove(journalKey(this.scope('bible_form',this.entityId),this.tabId),sequence);
      await this.journal.remove(this.indexKey,sequence);
      if(this.adopting){const row=this.adopting;await this.removeEntry(row);this.recoveries=this.recoveries.filter(entry=>entry.key!==row.key);this.adopting=null;}
      return await this.acknowledge(base,draft,sequence);
    } catch(error){this.localError=error;if(!this.conflict&&this.state!=='auth_lost')this.state='save_failed';this.emit();throw error;}
  }
  async acknowledge(base,draft,throughSequence=this.sequence) {
    this.clearTimers();await this.work;
    try {
      await this.journal.remove(journalKey(this.scope('bible_form',this.entityId),this.tabId),throughSequence);
      await this.journal.remove(this.indexKey,throughSequence);
    } catch { /* A real shared ACK remains authoritative; a leftover private checkpoint is safe to review later. */ }
    if(this.sequence!==throughSequence)return false;
    this.dirty=false;this.localError=null;this.identityRequested=false;this.identitySequence=-1;this.conflict=false;this.remote=null;
    this.base=copy(base);this.draft=copy(draft);this.entityId=base?.bibleId || 'new';this.state=this.recoveries.length?'recovery':'saved';this.emit();return true;
  }
  dispose(){this.clearTimers();this.notify=()=>{};}
}
