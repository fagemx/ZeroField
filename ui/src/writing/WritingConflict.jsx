import { useState } from 'react';
import { useTranslation } from '../i18n/react.jsx';
import { documentText,stable,clone } from './writingModel.js';
const p='writing.authoring.';
export function WritingConflict({persistence,fetchServer,onError,onDownload}) {
  const {t}=useTranslation();const [server,setServer]=useState(null),[chosen,setChosen]=useState([]),[busy,setBusy]=useState(false),[keepMetadata,setKeepMetadata]=useState(false);
  const local=persistence.doc;
  const run=async fn=>{setBusy(true);try{await fn();}catch(error){onError(error);}finally{setBusy(false);}};
  const nodes=new Map((local.content || []).map(node=>[node.attrs?.bid,node]));
  const remote=new Map((server?.doc.content || []).map(node=>[node.attrs?.bid,node]));
  const bids=[...new Set([...nodes.keys(),...remote.keys()])].filter(bid=>bid && stable(nodes.get(bid))!==stable(remote.get(bid)));
  const merge=async()=>{
    const doc=clone(server.doc);
    for(const bid of chosen){const node=nodes.get(bid),at=doc.content.findIndex(node=>node.attrs?.bid===bid);
      if(!node){if(at>=0)doc.content.splice(at,1);}
      else if(at>=0)doc.content[at]=clone(node);
      else {const localAt=local.content.findIndex(node=>node.attrs?.bid===bid),previous=local.content[localAt-1]?.attrs?.bid;const after=previous?doc.content.findIndex(node=>node.attrs?.bid===previous):-1;doc.content.splice(after+1,0,clone(node));}
    }
    await persistence.resolveWithCurrentBase(doc,server,{keepMetadata});
  };
  return <section role="alert" className="writing-conflict"><h2>{t(p+'conflict')}</h2><p>{t(p+'conflictExplanation')}</p><button type="button" onClick={onDownload}>{t(p+'downloadDraft')}</button>
    <button type="button" disabled={busy} onClick={()=>run(async()=>{setServer(await fetchServer());setChosen([]);})}>{t(p+'loadConflictBase')}</button>
    {server&&<><p>{t(p+'mergeExplanation')}</p>{persistence.resourceRef.kind==='source'&&<div><label><input type="checkbox" checked={keepMetadata} onChange={event=>setKeepMetadata(event.target.checked)}/>{t(p+'keepDeviceMetadata')}</label><div className="writing-compare-columns"><pre>{JSON.stringify({structure:server.structure,composition:server.composition},null,2)}</pre><pre>{JSON.stringify({structure:persistence.draftStructure,composition:persistence.draftComposition},null,2)}</pre></div></div>}{bids.map(bid=><article key={bid}>
      <label><input type="checkbox" checked={chosen.includes(bid)} disabled={busy} onChange={event=>setChosen(items=>event.target.checked?[...items,bid]:items.filter(item=>item!==bid))}/>{t(p+'useDeviceBlock',{id:bid})}</label>
      <div className="writing-compare-columns"><div><h3>{t(p+'serverCopy')}</h3><pre>{documentText(remote.get(bid)) || t(p+'removedBlock')}</pre></div><div><h3>{t(p+'deviceCopy')}</h3><pre>{documentText(nodes.get(bid)) || t(p+'removedBlock')}</pre></div></div>
    </article>)}<button type="button" disabled={busy} onClick={()=>run(merge)}>{t(p+'saveExplicitMerge')}</button></>}
  </section>;
}
