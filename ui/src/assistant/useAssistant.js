import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api.js";
import { guessKind, openReply } from "./text.js";
import { openReplies, resolveAgentTarget } from './agentModel.js';
import { useOrchestration } from './useOrchestration.js';

const FAST = 1000;   // 正在回答：1 秒看一次（回答邊寫邊存，畫面跟著長出來）
const SLOW = 30000;  // 沒在回答：30 秒看一次（負責人的回覆、狀態變化）
const MAX_FILES = 5;
const MAX_BYTES = 8 * 1024 * 1024;

export function useAssistant(slug, enabled, open, onError, onApplied, privacyMode = "full_access") {
  const [state, setState] = useState(null);
  const [sending, setSending] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState('coordinator');
  const [proposalErrors, setProposalErrors] = useState({});
  const [scope, setScopeState] = useState(null);
  const scopeRef = useRef(null);
  const setScope = useCallback((next) => {
    scopeRef.current = next ? structuredClone(next) : null;
    setScopeState(scopeRef.current);
  }, []);
  const base = `/projects/api/${slug}/assistant`;
  const currentBase = useRef(base);
  currentBase.current = base;
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const reload = useCallback(async () => {
    if (!enabled) return null;
    try {
      const data = await api.get(base);
      if (alive.current && currentBase.current === base) setState(data);
      return data;
    } catch (error) {
      if (error.status !== 403) onError(error.message);
      return null;
    }
  }, [base, enabled, onError]);
  const orchestration = useOrchestration(slug, enabled, open, onApplied, reload);

  useEffect(() => { reload(); }, [reload]);

  const busy = Boolean(openReply(state && state.thread));
  const busyForSelectedAgent = openReplies(state?.thread).has(selectedAgent);
  useEffect(() => {
    if (!enabled || !open) return undefined;
    // 一打開就先讀一次（關著的時候不會更新，不然要等 30 秒才看得到新的對話）；
    // 之後上一次讀完才排下一次：網路慢的時候不會一秒疊一個請求
    let stopped = false;
    let timer = null;
    const tick = async () => {
      await reload();
      if (!stopped) timer = setTimeout(tick, busy ? FAST : SLOW);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [enabled, open, busy, reload]);

  // 附件：先上傳（還沒綁到哪一句），送出時一起帶。放在這裡，側邊欄和工作區切換時不會掉。
  const [files, setFiles] = useState([]);
  const filesRef = useRef(files);
  filesRef.current = files;
  const seq = useRef(0);

  const patchFile = (key, patch) => setFiles((list) => list.map((f) => (f.key === key ? { ...f, ...patch } : f)));
  const dropFile = (key) => setFiles((list) => {
    const gone = list.find((f) => f.key === key);
    if (gone && gone.local) URL.revokeObjectURL(gone.local);
    return list.filter((f) => f.key !== key);
  });

  const addFiles = useCallback((incoming) => {
    const room = MAX_FILES - filesRef.current.length;
    const picked = [...(incoming || [])];
    if (picked.length > room) onError(`一次最多附 ${MAX_FILES} 個檔案`);
    for (const file of picked.slice(0, Math.max(0, room))) {
      if (file.size > MAX_BYTES) {
        onError(`「${file.name}」超過 8 MB`);
        continue;
      }
      seq.current += 1;
      const key = `f${seq.current}`;
      const kind = guessKind(file);
      const local = kind === "image" ? URL.createObjectURL(file) : "";
      setFiles((list) => [...list, { key, name: file.name, kind, local, status: "uploading", attachment: null }]);
      api.upload(`${base}/attachments`, file, file.name).then((result) => {
        patchFile(key, { status: "ready", attachment: result.attachment, kind: result.attachment.kind });
      }).catch((error) => {
        onError(`「${file.name}」沒附上：${error.message}`);
        dropFile(key);
      });
    }
  }, [base, onError]);

  const removeFile = useCallback((key) => {
    const found = filesRef.current.find((f) => f.key === key);
    if (found && found.attachment) api.post(`${base}/attachments/${found.attachment.id}/delete`).catch(() => {});
    dropFile(key);
  }, [base]);

  const send = useCallback(async (text, { agentKey } = {}) => {
    setSending(true);
    try {
      const ready = filesRef.current.filter((f) => f.status === "ready").map((f) => f.attachment.id);
      const sentScope = scopeRef.current;
      const target = resolveAgentTarget(text, agentKey || selectedAgent, state?.agents || []);
      const result = await api.post(`${base}/messages`, { text, agent_key: target, attachments: ready, ...(sentScope ? { scope: sentScope } : {}) });
      if (currentBase.current !== base) return null;
      if (scopeRef.current === sentScope) setScope(null);
      setFiles((list) => {
        list.filter(f => ready.includes(f.attachment?.id)).forEach((f) => f.local && URL.revokeObjectURL(f.local));
        return list.filter(f => !ready.includes(f.attachment?.id));
      });
      await reload();
      return result;
    } catch (error) {
      onError(error.message);
      return null;
    } finally {
      setSending(false);
    }
  }, [base, reload, onError, setScope, selectedAgent, state?.agents]);

  // 一段一段的對話：開新的、看以前的、接著以前的聊
  const replaceState = useCallback(async (path) => {
    try {
      const data = await api.post(path);
      if (alive.current) setState(data);
      return data;
    } catch (error) {
      onError(error.message);
      return null;
    }
  }, [onError]);
  const newConversation = useCallback(() => replaceState(`${base}/conversations`), [base, replaceState]);
  const resumeConversation = useCallback((id) => replaceState(`${base}/conversations/${id}/resume`), [base, replaceState]);
  const listConversations = useCallback(async () => {
    try {
      return (await api.get(`${base}/conversations`)).conversations;
    } catch (error) {
      onError(error.message);
      return null;
    }
  }, [base, onError]);
  const loadConversation = useCallback(async (id) => {
    try {
      return await api.get(`${base}/conversations/${id}`);
    } catch (error) {
      onError(error.message);
      return null;
    }
  }, [base, onError]);

  const decide = useCallback(async (proposal, verb, content, options = {}) => {
    setProposalErrors(current => ({ ...current, [proposal.id]: '' }));
    try {
      const result = await api.post(`${base}/proposals/${proposal.id}/${verb}`, verb === "apply" ? { content, ...options } : {});
      await reload();
      if (verb === "apply" && onApplied) onApplied(result.proposal, result.notes || []);
      return result;
    } catch (error) {
      setProposalErrors(current => ({ ...current, [proposal.id]: error.message }));
      onError(error.message);
      await reload();
      setState((current) => current ? { ...current, proposals: (current.proposals || []).map((p) => p.id === proposal.id ? { ...p, error: error.message } : p) } : current);
      return null;
    }
  }, [base, reload, onError, onApplied]);

  return {
    ...orchestration,
    privacyMode,
    slug, state, sending, busy, reload, send,
    selectedAgent, setSelectedAgent, busyForSelectedAgent, anyReplyBusy: busy,
    proposalErrors,
    scope, setScope,
    apply: (proposal, content, options) => decide(proposal, "apply", content, options),
    dismiss: (proposal) => decide(proposal, "dismiss"),
    files, addFiles, removeFile, uploading: files.some((f) => f.status === "uploading"),
    newConversation, resumeConversation, listConversations, loadConversation,
  };
}
