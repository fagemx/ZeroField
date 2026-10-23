import {createWritingJournal,journalKey,journalScope} from './writingJournal.js';
import {clone,stable} from './writingModel.js';
import {mutationId} from './writingTransport.js';

// Metadata-only adapter over the same bounded, actor-scoped manuscript journal.
// A draft retains the structure CAS it was authored against, including after reload.
export class WritingOutlineRecovery {
  constructor({slug,actorId,epId,transport,journal=createWritingJournal(),tabId=mutationId(),notify=()=>{},flushDocument=async()=>true,delay=800,maxDelay=5000}) {
    Object.assign(this,{transport,journal,tabId,notify,flushDocument,delay,maxDelay});
    this.scope=journalScope({slug,actorId,epId,resourceKind:'outline_metadata',resourceId:'main'});this.key=journalKey(this.scope,tabId);
    this.draft={scenePatches:[],lanePatches:[]};this.sequence=0;this.ackSequence=0;this.durableSequence=-1;this.identitySequence=-1;
    this.state='recovery';this.recoveries=[];this.work=Promise.resolve();this.preserved=new Map();
  }
  snapshot(){return {state:this.state,dirty:this.isDirty(),recoverable:!this.localError&&(this.dirty()?this.durableSequence===this.sequence:this.recoveries.length>0),draft:this.draft,recoveries:this.recoveries,baseVersion:this.base?.version,base:this.base,error:this.error,localError:this.localError,conflict:this.conflict};}
  recoveryState(){const {state,recoverable}=this.snapshot();return {state,recoverable};}
  dirty(){return this.sequence>this.ackSequence;}
  isDirty(){return this.dirty()||this.recoveries.length>0;}
  emit(){if(!this.disposed)this.notify(this.snapshot());}
  refresh(structure){if(!this.isDirty()&&!this.pending&&(!this.base||structure.version>=this.base.version)){this.base=clone(structure);this.emit();return true;}return false;}
  async discover(){
    try{this.recoveries=(await this.journal.list(this.scope)).filter(row=>row.draft&&row.base);this.discovered=true;this.state=this.recoveries.length?'recovery':'saved';this.localError=null;}
    catch(error){this.discovered=true;this.localError=error;this.state='save_failed';}
    this.emit();
  }
  change(scenePatch,lanePatch){
    if(this.disposed||!this.base||!this.discovered||this.recoveries.length||this.state==='auth_lost')return;
    const draft=clone(this.draft);
    for(const [kind,patch,key] of [['scenePatches',scenePatch,'sceneKey'],['lanePatches',lanePatch,'laneId']])if(patch){
      const index=draft[kind].findIndex(item=>item[key]===patch[key]);
      if(index<0)draft[kind].push(clone(patch));else draft[kind][index]={...draft[kind][index],...clone(patch)};
    }
    if(stable(draft)===stable(this.draft))return;
    this.draft=draft;this.sequence++;this.identitySequence=-1;if(!this.conflict)this.state='dirty';
    this.checkpoint();this.schedule();this.emit();
  }
  clearTimers(){clearTimeout(this.timer);clearTimeout(this.maximum);this.timer=null;this.maximum=null;}
  schedule(){
    if(this.disposed||this.reviewRequired||this.conflict||this.state==='auth_lost'||this.recoveries.length||!this.dirty()||this.composing)return;
    clearTimeout(this.timer);this.timer=setTimeout(()=>this.save(),this.delay);this.maximum ||= setTimeout(()=>this.save(),this.maxDelay);
  }
  setComposing(value){this.composing=value;if(value)this.clearTimers();else this.schedule();}
  checkpoint(){
    if(!this.dirty())return this.work;
    const sequence=this.sequence,value={scope:this.scope,tabId:this.tabId,base:clone(this.base),draft:clone(this.draft),pending:this.pending?clone(this.pending):null,localSequence:sequence,updatedAt:new Date().toISOString()};
    this.work=this.work.catch(()=>{}).then(()=>this.journal.put(this.key,value)).then(async()=>{
      if(this.sequence===sequence){this.durableSequence=sequence;this.localError=null;
        if(this.adopting){const row=this.adopting;if(row.key!==this.key)await this.journal.remove(row.key,row.localSequence);this.adopting=null;this.recoveries=this.recoveries.filter(item=>item.key!==row.key);}
        if(this.state==='save_failed')this.state='local_only';}
      this.emit();return true;
    }).catch(error=>{this.localError=error;if(!this.conflict&&this.state!=='auth_lost'&&this.state!=='saving')this.state='save_failed';this.emit();return false;});
    return this.work;
  }
  async save({explicit=false}={}){
    this.clearTimers();if(this.inflight)return this.inflight;
    if(this.reviewRequired&&!explicit)return false;if(explicit)this.reviewRequired=false;
    if(this.disposed||this.composing||this.conflict||this.state==='auth_lost'||this.recoveries.length||!this.dirty())return !this.isDirty();
    const pending=this.pending ||= {body:{baseVersion:this.base.version,clientMutationId:mutationId(),...clone(this.draft)},sequence:this.sequence};
    this.state='saving';this.emit();
    this.inflight=(async()=>{
      try{
        await this.checkpoint();
        if(this.disposed||!await this.flushDocument({requireServer:true})||this.disposed){if(!this.disposed)this.state=this.durableSequence===this.sequence&&!this.localError?'local_only':'save_failed';return false;}
        const ack=await this.transport('structure/metadata','PATCH',pending.body);
        if(ack.clientMutationId!==pending.body.clientMutationId||!Number.isInteger(ack.version))throw Object.assign(new Error('Unexpected outline acknowledgement'),{status:409});
        // Only clear fields ACKed at that exact value; edits made in flight form the next batch.
        for(const [kind,key] of [['scenePatches','sceneKey'],['lanePatches','laneId']]){
          this.draft[kind]=this.draft[kind].flatMap(patch=>{
            const sent=pending.body[kind].find(item=>item[key]===patch[key]);if(!sent)return [patch];
            const remaining=Object.fromEntries(Object.entries(patch).filter(([field,value])=>field===key||stable(value)!==stable(sent[field])));
            return Object.keys(remaining).length>1?[remaining]:[];
          });
        }
        this.base=clone(ack);this.ackSequence=pending.sequence;this.pending=null;this.error=null;this.conflict=null;
        if(this.dirty()){this.state='dirty';await this.checkpoint();}else{this.state='saved';await this.work;await this.journal.remove(this.key,pending.sequence).catch(()=>{});this.localError=null;}
        return true;
      }catch(error){
        await this.work; // A newer edit may still be checkpointing while this request fails.
        this.error=error;
        if([401,403].includes(error.status))this.state='auth_lost';
        else if(error.status===409){this.conflict=true;this.state='conflict';}
        else{if([400,413,422].includes(error.status)){this.pending=null;await this.checkpoint();}this.state=this.durableSequence===this.sequence&&!this.localError?'local_only':'save_failed';}
        return false;
      }finally{this.emit();}
    })();
    let result;try{result=await this.inflight;}finally{this.inflight=null;this.emit();}
    if(result&&this.dirty())this.schedule();return result;
  }
  async flush({reason='navigation',requireServer=false}={}){
    this.clearTimers();if(!this.discovered||this.localError&&!this.isDirty())return false;
    if(reason==='identity'){
      // An account change requires explicit same-sequence preservation, never implicit publication.
      try{const rows=await this.journal.list(this.scope);this.recoveries=this.recoveries.map(row=>rows.find(next=>next.key===row.key)||row);}catch(error){this.localError=error;this.emit();return false;}
      return (!this.dirty()||this.identitySequence===this.sequence&&!this.localError)&&this.recoveries.every(row=>this.preserved.get(row.key)===row.localSequence);
    }
    if(!this.isDirty())return this.state!=='auth_lost';
    await this.checkpoint();if(this.composing||this.conflict||this.state==='auth_lost'||this.recoveries.length)return false;
    if(this.reviewRequired&&reason!=='save'){if(!this.localError&&this.durableSequence===this.sequence){this.state='local_only';this.emit();return !requireServer;}return false;}
    while(this.dirty()){if(!await this.save({explicit:reason==='save'}))break;}
    return !this.dirty()||!requireServer&&!this.localError&&this.durableSequence===this.sequence;
  }
  async preserveIdentity(){const sequence=this.sequence;await this.checkpoint();if(!this.localError&&this.sequence===sequence&&this.durableSequence===sequence)this.identitySequence=sequence;this.emit();}
  async preserveRecovery(row){const fresh=(await this.journal.list(this.scope)).find(item=>item.key===row.key);if(fresh&&fresh.localSequence===row.localSequence)this.preserved.set(row.key,row.localSequence);this.emit();}
  async restore(row,current){
    if(this.dirty()||!this.recoveries.some(item=>item.key===row.key))return false;
    this.base=clone(row.base);this.draft=clone(row.draft);this.sequence++;this.pending=row.pending?{...clone(row.pending),sequence:stable(row.pending.body.scenePatches)===stable(row.draft.scenePatches)&&stable(row.pending.body.lanePatches)===stable(row.draft.lanePatches)?this.sequence:this.sequence-1}:null;
    this.conflict=row.base.version!==current.version;this.state=this.conflict?'conflict':'local_only';this.adopting=row;this.reviewRequired=true;
    await this.checkpoint();this.emit();return true; // Restoring is review, not publication or automatic retry.
  }
  async discardRecovery(row){await this.journal.remove(row.key,row.localSequence);this.recoveries=this.recoveries.filter(item=>item.key!==row.key);if(!this.isDirty())this.state='saved';this.emit();}
  async discard(current){
    if(this.inflight)return false;this.clearTimers();await this.work;
    try{await this.journal.remove(this.key,this.sequence);if(this.adopting)await this.discardRecovery(this.adopting);}
    catch(error){this.localError=error;this.emit();return false;}
    this.base=clone(current);this.draft={scenePatches:[],lanePatches:[]};this.ackSequence=this.sequence;this.pending=null;this.conflict=null;this.error=null;this.localError=null;this.identitySequence=-1;this.adopting=null;this.reviewRequired=false;this.state=this.recoveries.length?'recovery':'saved';this.emit();return true;
  }
  dispose(){this.clearTimers();this.disposed=true;this.notify=()=>{};}
}
