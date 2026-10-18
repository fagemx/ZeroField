import { t as uiText } from '../i18n/index.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { emptyBoard, reconcileBoard, cancellationRequest } from './orchestrationModel.js';

export function useOrchestration(slug, enabled, open, onApplied, reloadAssistant) {
  const [board, setBoard] = useState(emptyBoard), [boardOpen, setBoardOpen] = useState(false), [boardError, setBoardError] = useState('');
  const [paged, setPaged] = useState(false);
  const currentSlug = useRef(slug), callbacks = useRef({ onApplied, reloadAssistant }), pagedRef = useRef(false);
  currentSlug.current = slug; callbacks.current = { onApplied, reloadAssistant };
  const base = `/projects/api/${slug}/orchestration`;
  const reloadBoard = useCallback(async (full = true) => {
    if (!enabled) return null;
    const data = await api.get(`${base}/board?${full ? 'limit=50' : 'counts_only=true'}`);
    if (currentSlug.current === slug) {
      setBoard(current => full ? reconcileBoard(current, data, { responseSlug: slug, currentSlug: currentSlug.current }) : { ...current, counts: data.counts });
      setBoardError('');
      if (full) { pagedRef.current = false; setPaged(false); }
    }
    return data;
  }, [base, slug, enabled]);
  useEffect(() => { setBoard(emptyBoard()); setBoardOpen(false); setBoardError(''); setPaged(false); pagedRef.current = false; }, [slug]);
  const active = Boolean(board.counts?.working || board.counts?.needs_you);
  useEffect(() => {
    if (!enabled) return undefined;
    let stopped = false, timer;
    const poll = async () => {
      try { await reloadBoard(open && boardOpen && !pagedRef.current); }
      catch (error) { if (!stopped && currentSlug.current === slug) setBoardError(error.message); }
      if (!stopped) timer = setTimeout(poll, active ? 1000 : 30000);
    };
    poll(); return () => { stopped = true; clearTimeout(timer); };
  }, [slug, enabled, open, boardOpen, active, reloadBoard]);
  const updateBoardUi = useCallback(patch => setBoard(current => ({ ...current, ui: { ...current.ui, ...patch } })), []);
  const moreBoard = useCallback(async () => {
    if (!board.cursor) return;
    const data = await api.get(`${base}/board?limit=50&cursor=${encodeURIComponent(board.cursor)}`);
    if (currentSlug.current !== slug) return;
    setBoard(current => {
      const merged = { ...data };
      for (const key of ['needs_you', 'working', 'done', 'idle']) merged[key] = [...new Map([...current[key], ...data[key]].map(row => [row.id, row])).values()];
      return reconcileBoard(current, merged);
    });
    pagedRef.current = true; setPaged(true);
  }, [base, board.cursor, slug]);
  const mutate = useCallback(async (path, body) => {
    if (currentSlug.current !== slug) throw new Error(uiText("useOrchestration.theWorkspaceChangedReopenThisTask"));
    const data = await api.post(path, body);
    if (currentSlug.current !== slug) return data;
    if (data.proposal?.status === 'applied') callbacks.current.onApplied?.(data.proposal, []);
    await Promise.all([reloadBoard(true), callbacks.current.reloadAssistant?.()]);
    return data;
  }, [slug, reloadBoard]);
  const startRun = useCallback(body => mutate(`${base}/runs`, body), [base, mutate]);
  const resolveGate = useCallback((id, body) => mutate(`${base}/gates/${id}/resolve`, body), [base, mutate]);
  const cancelWork = useCallback(item => {
    const request = cancellationRequest(base, slug, item);
    return mutate(request.path, request.body);
  }, [base, slug, mutate]);
  const retryWork = useCallback(item => mutate(`${base}/tasks/${item.task_id}/retry`, { client_request_id: crypto.randomUUID() }), [base, mutate]);
  return { board, boardError, boardOpen, setBoardOpen, updateBoardUi, reloadBoard, moreBoard, paged,
    orchestrationCounts: board.counts, startRun, resolveGate, cancelWork, retryWork };
}
