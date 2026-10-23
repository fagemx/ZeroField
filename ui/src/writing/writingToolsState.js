import {createElement, useCallback, useEffect, useRef, useState} from 'react';
import {retryable, toolsErrorKey} from './writingToolsModel.js';

export function ToolsNotice({task, t}) {
  return createElement('div', {'aria-live': 'polite'},
    task.busy && createElement('p', {role: 'status'}, t('writing.tools.busy')),
    task.error && createElement('p', {role: 'alert'}, t(`writing.tools.${task.error}`)),
    task.retry && createElement('button', {type: 'button', onClick: task.retry, disabled: task.busy}, t('writing.tools.retry')));
}

// Authorized catalog summaries only; no second editable source/document store.
export function useToolsResourceCatalog(workspace) {
  const [pages,setPages] = useState({});
  const catalogs = {};
  for (const kind of ['versions','branches']) {
    const field = kind === 'versions' ? 'versionId' : 'branchId';
    const unique = new Map([...(pages[kind]?.items || []),...(workspace?.[kind]?.items || [])].map(item => [item[field],item]));
    catalogs[kind] = {items:[...unique.values()],nextCursor:pages[kind]?.nextCursor !== undefined ? pages[kind].nextCursor : workspace?.[kind]?.nextCursor};
  }
  async function loadMore(kind,transport,signal) {
    const cursor=catalogs[kind].nextCursor;
    if (!cursor) return;
    const query=new URLSearchParams({cursor,limit:'20'});
    const result=await transport(`${kind}?${query}`,'GET',undefined,{signal});
    signal?.throwIfAborted();
    setPages(previous=>({...previous,[kind]:{items:[...(previous[kind]?.items || []),...result.items],nextCursor:result.nextCursor}}));
  }
  return {workspace:{...workspace,...catalogs},loadMore};
}

export function useToolsAction(onError) {
  const [state, setState] = useState({busy: false, error: null, retry: null});
  const active = useRef(true);
  const running = useRef(false);
  const controller = useRef(null);
  const errorCallback = useRef(onError);
  errorCallback.current = onError;
  useEffect(() => { active.current = true; return () => { active.current = false; controller.current?.abort(); running.current = false; }; }, []);
  const run = useCallback(async (request, accepted) => {
    if (running.current || !active.current) return;
    running.current = true;
    const current = new AbortController();
    controller.current = current;
    setState({busy: true, error: null, retry: null});
    try {
      const result = await request(current.signal);
      if (!active.current || current.signal.aborted) return;
      await accepted?.(result, current.signal);
      if (active.current && !current.signal.aborted) setState({busy: false, error: null, retry: null});
      return result;
    } catch (error) {
      if (!active.current || current.signal.aborted) return;
      setState({busy: false, error: toolsErrorKey(error), retry: retryable(error) ? () => run(request, accepted) : null});
      errorCallback.current?.(error);
    } finally { if (controller.current === current) running.current = false; }
  }, []);
  return {...state, run, clear: () => setState({busy: false, error: null, retry: null})};
}
