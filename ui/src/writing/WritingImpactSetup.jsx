import { useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
const p='writing.authoring.';
export function WritingImpactSetup({targetRef,structure,shots=[],confirmBaseline,writable,onPreview}) {
  const {t}=useTranslation();
  const [confirm,setConfirm]=useState(confirmBaseline),[selected,setSelected]=useState([]),[bindings,setBindings]=useState([]),[shot,setShot]=useState(''),[scene,setScene]=useState(''),[beat,setBeat]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(null);
  const scenes=structure?.initialized===false?[]:structure?.scenes || [],active=scenes.find(item=>item.sceneKey===scene);
  const submit=async()=>{setBusy(true);setError(null);try{await onPreview({targetRef,confirmBaseline:confirm,...(selected.length?{shotIds:selected}:{}),...(bindings.length?{bindings}:{})});}catch(error){setError(error);}finally{setBusy(false);}};
  return <section className="writing-impact-setup" aria-label={t(p+'impactSetup')}><h2>{t(p+'impactSetup')}</h2><p>{t(p+'impactTarget',{target:targetRef.kind==='working'?t(p+'workingScript'):targetRef.id})}</p>
    <fieldset disabled={!writable||busy}><legend>{t(p+'impactScope')}</legend>
      <label><input type="checkbox" checked={confirm} onChange={event=>setConfirm(event.target.checked)}/>{t(p+'confirmImpactBaseline')}</label>
      <p>{t(p+'impactScopeHelp')}</p>
      {shots.map(item=><label key={item.shotId}><input type="checkbox" checked={selected.includes(item.shotId)} onChange={event=>setSelected(ids=>event.target.checked?[...ids,item.shotId]:ids.filter(id=>id!==item.shotId))}/>{item.shotIndex || item.shotId}</label>)}
      <details><summary>{t(p+'explicitBindings')}</summary><p>{t(p+'bindingHonesty')}</p>
        <label>{t(p+'bindingShot')}<select aria-label={t(p+'bindingShot')} value={shot} onChange={event=>setShot(event.target.value)}><option value="">{t(p+'choose')}</option>{shots.map(item=><option key={item.shotId} value={item.shotId}>{item.shotIndex || item.shotId}</option>)}</select></label>
        <label>{t(p+'bindingScene')}<select aria-label={t(p+'bindingScene')} value={scene} onChange={event=>{setScene(event.target.value);setBeat('');}}><option value="">{t(p+'choose')}</option>{scenes.map(item=><option key={item.sceneKey} value={item.sceneKey}>{item.title || item.sceneKey}</option>)}</select></label>
        <label>{t(p+'bindingBeat')}<select aria-label={t(p+'bindingBeat')} value={beat} onChange={event=>setBeat(event.target.value)}><option value="">{t(p+'sceneOnlyBinding')}</option>{(active?.beats || []).map(item=><option key={item.beatKey} value={item.beatKey}>{item.beatKey}</option>)}</select></label>
        <button type="button" disabled={!shot||!scene} onClick={()=>{setBindings(items=>[...items.filter(item=>item.shotId!==shot),{shotId:shot,sceneKeys:[scene],beatKeys:beat?[beat]:[]}]);if(selected.length&&!selected.includes(shot))setSelected(ids=>[...ids,shot]);}}>{t(p+'addBinding')}</button>
        {bindings.map(item=><p key={item.shotId}>{item.shotId} → {[...item.sceneKeys,...item.beatKeys].join(' · ')} <button type="button" onClick={()=>setBindings(items=>items.filter(binding=>binding!==item))}>{t(p+'removeBinding')}</button></p>)}
      </details>
      <button type="button" className="writing-primary" onClick={submit}>{t(p+'previewImpact')}</button>
    </fieldset>{error&&<p role="alert">{error.message}</p>}
  </section>;
}
