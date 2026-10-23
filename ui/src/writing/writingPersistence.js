import { clone, stable, mergeAcknowledged, documentOps, sourceStructureForDoc } from './writingModel.js';
import { journalKey } from './writingJournal.js';
import { mutationId } from './writingTransport.js';

// One instance per actor/episode/resource. No global mutable draft or retry state.
export class WritingPersistence {
  constructor({resourceRef,initial,transport,journal,scope,tabId,notify=()=>{},delay=800,maxDelay=5000,clock=globalThis}) {
    Object.assign(this,{resourceRef,transport,journal,scope,tabId,notify,delay,maxDelay,clock});
    this.key=journalKey(scope,tabId); this.base=clone(initial); this.doc=clone(initial.doc);this.draftStructure=clone(initial.structure || {});this.draftComposition=clone(initial.composition || {});
    this.sequence=0; this.ackSequence=0; this.journalSequence=0; this.composing=false;
    this.state='saved'; this.stopped=false; this.disposed=false; this.sessionId=mutationId();
    this.journalWork=Promise.resolve(); this.recoveries=[];
  }
  snapshot() { return {state:this.state,dirty:this.isDirty(),recoverable:this.recoveries.length>0 || this.journalSequence>=this.sequence && this.isDirty(),doc:this.doc,docHash:this.base.docHash,version:this.base.version,structure:this.draftStructure,composition:this.draftComposition,savedAt:this.base.savedAt,error:this.error,localError:this.localError,recoveries:this.recoveries,conflict:this.conflict}; }
  emit() { if (!this.disposed) this.notify(this.snapshot()); }
  isDirty() { return this.sequence>this.ackSequence; }
  recoveryState() { return {state:this.state,recoverable:this.recoveries.length>0 || this.journalSequence>=this.sequence && this.isDirty()}; }
  async discover() {
    try {
      const entries=await this.journal.list(this.scope);
      if (this.disposed) return [];
      const synced=entry=>stable(entry.doc)===stable(this.base.doc) && (this.resourceRef.kind==='working' || stable(entry.structure || {})===stable(this.base.structure || {}) && stable(entry.composition || {})===stable(this.base.composition || {}));
      this.recoveries=entries.filter(entry=>!synced(entry));
      for (const entry of entries.filter(synced)) await this.journal.remove(entry.key,entry.localSequence);
      if (this.recoveries.length) this.state='recovery';
    } catch(error) { this.localError=error; }
    this.emit(); return this.recoveries;
  }
  change(doc) {
    if (this.disposed || stable(doc)===stable(this.doc)) return;
    this.doc=clone(doc); this.sequence++;
    if (!this.stopped && !this.conflict && !this.recoveries.length) this.state='dirty';
    this.checkpoint(); this.schedule(); this.emit();
  }
  changeMetadata({structure=this.draftStructure,composition=this.draftComposition}={}) {
    if(this.disposed || stable(structure)===stable(this.draftStructure) && stable(composition)===stable(this.draftComposition))return;
    this.draftStructure=clone(structure);this.draftComposition=clone(composition);this.sequence++;
    if(!this.stopped&&!this.conflict&&!this.recoveries.length)this.state='dirty';this.checkpoint();this.schedule();this.emit();
  }
  setComposing(value) { this.composing=value; if (value) this.clearTimers(); else this.schedule(); }
  schedule() {
    if (this.disposed || this.composing || this.stopped || this.conflict || this.recoveries.length || !this.isDirty()) return;
    this.clock.clearTimeout(this.timer);
    this.timer=this.clock.setTimeout(()=>{this.save();},this.delay);
    this.maximum ||= this.clock.setTimeout(()=>{this.save();},this.maxDelay);
  }
  clearTimers() { this.clock.clearTimeout(this.timer);this.clock.clearTimeout(this.maximum);this.timer=null;this.maximum=null; }
  checkpoint() {
    const sequence=this.sequence;
    const value={scope:this.scope,tabId:this.tabId,resourceRef:this.resourceRef,baseHash:this.base.docHash,baseVersion:this.base.version,baseDoc:clone(this.base.doc),baseStructure:clone(this.base.structure || {}),baseComposition:clone(this.base.composition || {}),baseStructureFingerprint:stable(this.base.structure || {}),baseCompositionFingerprint:stable(this.base.composition || {}),doc:clone(this.doc),structure:clone(this.draftStructure),composition:clone(this.draftComposition),pending:this.pending ? clone(this.pending) : null,localSequence:sequence,updatedAt:new Date().toISOString()};
    const work=this.journalWork.catch(()=>{}).then(()=>this.journal.put(this.key,value)).then(()=>{
      this.journalSequence=Math.max(this.journalSequence,sequence); this.localError=null;
      if (this.isDirty() && this.state==='save_failed') this.state='local_only';
      this.emit(); return true;
    }).catch(error=>{this.localError=error;this.emit();return false;});
    this.journalWork=work; return work;
  }
  makePending() {
    const id=mutationId(),doc=clone(this.doc),sequence=this.sequence;
    let tail,method,body,complete=true,sent=doc;
    if (this.resourceRef.kind==='working') {
      tail='script/ops';method='POST';
      const all=documentOps(this.base.doc,doc),ops=[];
      let bytes=200;
      for(const op of all){const size=new TextEncoder().encode(JSON.stringify(op)).byteLength;if(ops.length>=200 || bytes+size>2800000)break;ops.push(op);bytes+=size;}
      if(all.length && !ops.length)throw Object.assign(new Error('Split this block before saving: its base and changes exceed the request limit.'),{status:413});
      complete=ops.length===all.length;
      if(!complete){
        sent=clone(this.base.doc);
        for(const op of ops){
          if(op.op==='put'){const at=sent.content.findIndex(node=>node.attrs?.bid===op.bid);if(at>=0)sent.content[at]=clone(op.node);else sent.content.splice(op.after?sent.content.findIndex(node=>node.attrs?.bid===op.after)+1:0,0,clone(op.node));}
          else if(op.op==='del')sent.content=sent.content.filter(node=>node.attrs?.bid!==op.bid);
          else if(op.op==='order'){const nodes=new Map(sent.content.map(node=>[node.attrs?.bid,node]));sent.content=op.bids.filter(id=>nodes.has(id)).map(id=>nodes.get(id));}
          else {const table=sent.content.find(node=>node.attrs?.bid===op.table);if(!table)continue;const at=table.content.findIndex(row=>row.attrs?.bid===op.rid);if(op.op==='del_row'){if(at>=0)table.content.splice(at,1);}else if(at>=0)table.content[at]=clone(op.node);else table.content.splice(op.after?table.content.findIndex(row=>row.attrs?.bid===op.after)+1:0,0,clone(op.node));}
        }
      }
      body={ops,clientMutationId:id,session_id:this.sessionId};
    } else {
      tail=this.resourceRef.kind==='source' ? `sources/${this.resourceRef.mode}` : `branches/${encodeURIComponent(this.resourceRef.id)}`;
      method='PUT';body={baseVersion:this.base.version || 0,clientMutationId:id,doc,structure:this.draftStructure,...(this.resourceRef.kind==='source' ? {composition:this.draftComposition} : {})};
    }
    return {tail,method,body,idempotencyKey:id,doc:sent,sequence,complete};
  }
  async save() {
    this.clearTimers();
    if (this.inflight) return this.inflight;
    if (this.disposed || this.composing || this.stopped || this.conflict || this.recoveries.length || !this.isDirty()) return !this.isDirty();
    try {this.pending ||= this.makePending();} catch(error){this.error=error;this.state=this.journalSequence>=this.sequence?'local_only':'save_failed';this.emit();return false;}
    const pending=this.pending;
    this.state='saving';this.emit();
    this.inflight=(async()=>{
      // Network can proceed if IDB fails; only a real server ACK can then make navigation safe.
      await this.checkpoint();
      if (this.disposed || this.stopped) return false;
      try {
        const ack=await this.transport(pending.tail,pending.method,pending.body,{idempotencyKey:pending.idempotencyKey});
        // Neither a late ACK nor a failed/aborted response may mutate/delete the old actor's recovery.
        if (this.disposed || this.stopped) return false;
        if (ack.clientMutationId!==pending.body.clientMutationId) throw Object.assign(new Error('Unexpected save acknowledgement'),{status:409});
        if (ack.conflicts?.length) {
          this.conflict={server:ack.doc,local:clone(this.doc),conflicts:ack.conflicts};this.state='conflict';this.error=null;await this.checkpoint();return false;
        }
        if (!ack.docHash) throw new Error('Save response has no content fingerprint');
        const server=ack.doc || pending.doc;
        this.doc=mergeAcknowledged(server,pending.doc,this.doc);
        this.base={...this.base,...ack,doc:clone(server)};
        if(pending.sequence===this.sequence){this.draftStructure=clone(ack.structure || this.draftStructure);this.draftComposition=clone(ack.composition || this.draftComposition);}
        if(pending.complete!==false)this.ackSequence=pending.sequence;this.pending=null;this.error=null;
        if (this.isDirty()) {this.state='dirty';await this.checkpoint();}
        else {
          this.state='saved';this.journalSequence=0;
          this.journalWork=this.journalWork.catch(()=>{}).then(()=>this.journal.remove(this.key,pending.sequence)).catch(error=>{this.localError=error;});
          await this.journalWork;
        }
        return true;
      } catch(error) {
        if (this.disposed || this.stopped) return false;
        this.error=error;
        if ([401,403].includes(error.status)) {this.stopped=true;this.state='auth_lost';}
        else if (error.status===409) {this.conflict={local:clone(this.doc),details:error.details || error.data?.details};this.state='conflict';}
        else {
          if([400,413,422].includes(error.status)){this.pending=null;await this.checkpoint();}
          this.state=this.journalSequence>=this.sequence ? 'local_only' : 'save_failed';
        }
        return false;
      } finally {this.inflight=null;this.emit();}
    })();
    const result=await this.inflight;
    // Only continue automatically after success. Network errors keep the exact retry body/key.
    if (result && this.isDirty()) this.schedule();
    return result;
  }
  async flush({requireServer=false}={}) {
    this.clearTimers();
    if (this.disposed) return false;
    if (!this.isDirty()) return !this.recoveries.length && !this.stopped && !this.conflict;
    await this.checkpoint();
    if (this.composing || this.stopped || this.conflict || this.recoveries.length) return false;
    while (this.isDirty()) { if (!await this.save()) break; }
    return !this.isDirty() || (!requireServer && !this.stopped && !this.conflict && this.journalSequence>=this.sequence);
  }
  refresh(next) {
    // A refresh must never turn a dirty editor into a remote overwrite or force rebase.
    if (this.isDirty() || this.composing || this.recoveries.length) return false;
    this.base=clone(next);this.doc=clone(next.doc);this.draftStructure=clone(next.structure || {});this.draftComposition=clone(next.composition || {});this.emit();return true;
  }
  recoveryDivergence(entry) {
    const content=entry.baseHash!==this.base.docHash;
    // Private CAS versions include chapter/lens changes, unlike coalesced mainline revisions.
    const metadata=this.resourceRef.kind!=='working' && (entry.baseVersion!==this.base.version ||
      entry.baseStructureFingerprint!=null && entry.baseStructureFingerprint!==stable(this.base.structure || {}) ||
      entry.baseCompositionFingerprint!=null && entry.baseCompositionFingerprint!==stable(this.base.composition || {}));
    return {content,metadata,metadataOnly:metadata&&!content};
  }
  async restore(entry) {
    if (this.disposed) return;
    if (!this.recoveries.some(item=>item.key===entry.key)) throw new Error('Unknown recovery');
    const server=clone(this.base),divergence=this.recoveryDivergence(entry);
    this.doc=clone(entry.doc);this.draftStructure=clone(entry.structure || this.base.structure || {});this.draftComposition=clone(entry.composition || this.base.composition || {});this.sequence++;this.recoveries=[];
    if(this.resourceRef.kind!=='working')this.base={...this.base,doc:clone(entry.baseDoc || this.base.doc),docHash:entry.baseHash,version:entry.baseVersion ?? 0,structure:clone(entry.baseStructure || {}),composition:clone(entry.baseComposition || {})};
    if (divergence.content || divergence.metadata) {
      this.pending=null;
      this.conflict={server:server.doc,serverMetadata:{structure:server.structure,composition:server.composition},local:entry.doc,base:entry.baseDoc,...divergence};this.state='conflict';
    } else {
      this.pending=entry.pending ? {...clone(entry.pending),sequence:stable(entry.pending.doc)===stable(entry.doc)?this.sequence:this.sequence-1} : null;
      this.state='dirty';
    }
    const durable=await this.checkpoint();
    if (durable && entry.key!==this.key) await this.journal.remove(entry.key,entry.localSequence);
    this.emit();if (!this.conflict) this.schedule();
  }
  async discardRecovery(entry) { await this.journal.remove(entry.key,entry.localSequence);this.recoveries=this.recoveries.filter(item=>item.key!==entry.key);if(!this.recoveries.length)this.state='saved';this.emit(); }
  async resolveWithCurrentBase(doc, server, {keepMetadata=false}={}) {
    // Called only by an explicit human merge decision with a freshly fetched server doc.
    this.pending=null;this.base=clone(server);this.conflict=null;this.doc=clone(doc);
    if(!keepMetadata){this.draftStructure=clone(server.structure || {});this.draftComposition=clone(server.composition || {});}
    if(this.resourceRef.kind==='source')this.draftStructure=sourceStructureForDoc(this.draftStructure,doc);
    this.sequence++;this.state='dirty';
    // Branches normally derive lens changes from their screenplay. An explicit conflict
    // choice instead freezes the selected metadata with this one replayable merge.
    if(this.resourceRef.kind==='branch'){this.pending=this.makePending();this.pending.body.composition=clone(this.draftComposition);}
    await this.checkpoint();this.emit();this.schedule();
  }
  dispose() {this.clearTimers();this.disposed=true;/* Keep the actor-scoped journal; ignore late ACKs. */}
}
