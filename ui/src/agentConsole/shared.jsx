import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { t } from '../i18n/index.js';
import { ApiError } from '../api.js';
import { pretty } from './model.js';

export const ConsoleContext = createContext(null);
export const useConsole = () => useContext(ConsoleContext);
export async function consoleRequest(base, path, {method='GET',body,signal}={}) {
  const response = await fetch(base+path, {method,signal,credentials:'same-origin',headers:{Accept:'application/json',...(method==='GET' ? {} : {'Content-Type':'application/json','X-Requested-With':'projects',...(method==='POST' ? {'Idempotency-Key':crypto.randomUUID()}:{})})},...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new ApiError(response.status, 'Console request failed', data);
  return data;
}
export function useLoad(path, revision=0) {
  const {request,revision:globalRevision} = useConsole();
  const [state,setState] = useState({});
  useEffect(() => {
    const controller = new AbortController();
    setState({loading:true});
    request(path,{signal:controller.signal}).then(data => {if(!controller.signal.aborted)setState({data});}).catch(error => {if(!controller.signal.aborted)setState({error});});
    return () => controller.abort();
  }, [path,request,revision,globalRevision]);
  return state;
}
export function useDraft(key, fallback) {
  const {draftKey} = useConsole();
  const storageKey = draftKey+':'+key;
  const load = () => {try {return JSON.parse(sessionStorage.getItem(storageKey)) ?? fallback;} catch {return fallback;}};
  const [value,setValue] = useState(load);
  const lastKey = useRef(storageKey);
  useEffect(() => {if(lastKey.current!==storageKey){lastKey.current=storageKey;setValue(load());}},[storageKey]); // identity/project boundary
  const update = next => setValue(current => {
    const result = typeof next === 'function' ? next(current) : next;
    try {sessionStorage.setItem(storageKey,JSON.stringify(result));} catch { /* The mounted draft remains available. */ }
    return result;
  });
  return [value,update];
}
export function Field({label,children}) {return <label className="ac-field"><span>{t('console.'+label)}</span>{children}</label>;}
export function TextField({label,value,onChange,multiline=false,...props}) {
  const Input = multiline ? 'textarea' : 'input';
  return <Field label={label}><Input aria-label={t('console.'+label)} value={value ?? ''} onChange={e=>onChange(e.target.value)} {...props}/></Field>;
}
export function SelectField({label,value,onChange,options,...props}) {return <Field label={label}><select aria-label={t('console.'+label)} value={value ?? ''} onChange={e=>onChange(e.target.value)} {...props}>{options.map(option=>typeof option==='string' ? <option key={option} value={option}>{t('console.values.'+option,{defaultValue:option})}</option> : <option key={option.value} value={option.value}>{option.label}</option>)}</select></Field>;}
export function Check({label,checked,onChange,...props}) {return <label className="ac-check"><input type="checkbox" checked={Boolean(checked)} onChange={e=>onChange(e.target.checked)} {...props}/>{t('console.'+label)}</label>;}
export function JsonView({value,label='result',open=false}) {return <details className="ac-json" open={open}><summary>{t('console.'+label)}</summary><pre>{pretty(value)}</pre></details>;}
export function Empty() {return <p className="ac-empty">{t('console.empty')}</p>;}
export function Loading({state}) {return state.loading ? <p role="status">{t('console.loading')}</p> : state.error ? <p role="alert">{t('console.loadFailed')}</p> : null;}
export function JsonField({label,value,onChange,disabled=false,rows=10}) {return <TextField label={label} multiline rows={rows} spellCheck={false} value={value} disabled={disabled} onChange={onChange}/>;}
export function History({path}) {
  const [open,setOpen] = useState(false);
  return <><button type="button" onClick={()=>setOpen(!open)}>{t('console.history')}</button>{open && <HistoryData path={path}/>}</>;
}
function HistoryData({path}) {const state=useLoad(path);return <><Loading state={state}/>{state.data && <JsonView label="history" value={state.data} open/>}</>;}
