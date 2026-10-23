// Scope this registry to one mounted actor/project/episode workspace, never globally.
export class WritingToolControls {
  constructor(onChanged=()=>{}) { this.entries=new Map();this.onChanged=onChanged; }
  register(key,control) {
    if(typeof key!=='string'||!key||!control||['flush','isDirty','recoveryState'].some(method=>typeof control[method]!=='function'))throw new TypeError('A tool control needs a key, flush, isDirty and recoveryState');
    const entry={control};this.entries.set(key,entry);this.onChanged();
    return ()=>{if(this.entries.get(key)===entry){this.entries.delete(key);this.onChanged();}};
  }
  states() {
    return [...this.entries].map(([key,{control}])=>{
      try {return {key,...control.recoveryState(),dirty:!!control.isDirty()};}
      catch {return {key,dirty:true,state:'save_failed',recoverable:false};}
    });
  }
  summary(document={state:'saved',dirty:false,recoverable:false}) {
    const tools=this.states(),dirty=document.dirty||tools.some(item=>item.dirty);
    const pending=[document,...tools].filter(item=>item.dirty||item.recoverable);
    const recoverable=pending.length>0&&pending.every(item=>item.recoverable || !item.dirty);
    const priority=['auth_lost','conflict','save_failed','recovery','local_only','saving','dirty'];
    const state=priority.find(state=>pending.some(item=>item.state===state)) || (dirty?'dirty':document.state);
    return {state,dirty,recoverable,documentState:document.state,tools};
  }
  async flush(options={}) {
    if(options.requireServer&&options.reason!=='identity')return true;
    // Snapshot registrations; an old control cannot grant safety for its replacement.
    try {
      for(const [key,entry] of [...this.entries]) {
        try {
          if(!await entry.control.flush({...options,reason:options.reason || 'navigation',requireServer:false}))return false;
          if(this.entries.get(key)!==entry)return false;
          const dirty=entry.control.isDirty(),state=entry.control.recoveryState();
          if(options.reason!=='identity'&&(dirty&&!state.recoverable || (dirty||state.recoverable)&&['auth_lost','conflict','recovery'].includes(state.state)))return false;
        } catch {return false;}
      }
      return true;
    } finally {this.onChanged();}
  }
}
