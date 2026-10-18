import { Fragment, useEffect, useRef, useState } from "react";

import { shortTime } from "../format.js";
import { ManagerPanel } from "./ManagerPanel.jsx";
import { TableProposalReview } from "./TableProposalReview.jsx";
import { AgentSelector } from './AgentSelector.jsx';
import { AgentBoard, OrchestrationCounters } from './AgentBoard.jsx';
import { agentSuggestions, resolveAgentTarget, messagePersona } from './agentModel.js';
import {
  appliedLabel, blocks, clip, currentFocus, documentUrl, inlineParts, isReportSource, lookedAt, progressCounts,
  sourceTarget,
  liveText, splitSources, taskLine, todoGroups, workingLine,
  ACCEPT_FILES, attachmentHint, clampWidth, elapsedSeconds, fileIcon, formatSeconds, isPicked, orphanPending,
  paneTab, paneTabs, pickTodo, proposalCopy,
} from "./text.js";

const INFO = (privacyMode) => (
  <>
    <b>它看得到：</b>專案畫布所有內容、報表索引的工作表／欄名／公式、團隊在頁面上的留言與標註。<br />
    <b>資料使用：</b>{privacyMode === "mask_numbers" ? "本專案已開啟數字遮罩；文字內容經遮罩後才交給模型，圖片附件停用。" : "本專案允許模型讀取完整內容，包含數字與你附上的圖片。"}它不會讀取別人的私人對話。<br />
    <b>要改專案頁：</b>一律先送出提案卡問你，你按確認才會放上去。
  </>
);
const STARTERS = ["整理這個專案的重點與待辦", "找出表格中缺少的資訊，先提出建議", "依文件內容，整理下一步工作"];

const COPY_ICON = (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
    <rect x="5.5" y="5.5" width="8" height="8" rx="1.6" />
    <path d="M10.5 5.5V3.6c0-.9-.7-1.6-1.6-1.6H3.6C2.7 2 2 2.7 2 3.6v5.3c0 .9.7 1.6 1.6 1.6h1.9" />
  </svg>
);
const CLIP_ICON = (
  <svg width="17" height="17" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
    <path d="M14.5 9.5l-5.3 5.3a3.3 3.3 0 0 1-4.7-4.7l6-6a2.2 2.2 0 0 1 3.1 3.1l-5.9 5.9a1.1 1.1 0 0 1-1.6-1.6l5.3-5.3" />
  </svg>
);

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // 沒有剪貼簿權限（例如不是 https）：退回選取再複製
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;opacity:0;top:0;left:0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    area.remove();
    return ok;
  }
}

function CopyButton({ text, title }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className={"icon-copy" + (done ? " done" : "")} title={done ? "已複製" : title} aria-label={title}
      onClick={async () => {
        if (await copyText(text || "")) {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        }
      }}>
      {done ? "✓" : COPY_ICON}
    </button>
  );
}

function attachmentUrl(slug, id, which) {
  return `/projects/api/${slug}/assistant/attachments/${id}/${which}`;
}

function Attachments({ slug, items, onZoom }) {
  if (!items || !items.length) return null;
  return (
    <div className="u-att">
      {items.map((a) => (a.kind === "image"
        ? <button type="button" key={a.id} className="u-img" title={`${a.name}（點開看大圖）`}
          onClick={() => onZoom && onZoom({ src: attachmentUrl(slug, a.id, "preview"), name: a.name })}>
          <img src={attachmentUrl(slug, a.id, "thumb")} alt={a.name} />
        </button>
        : <a key={a.id} className="u-file" href={attachmentUrl(slug, a.id, "file")} download={a.name}>{fileIcon(a.kind)} {a.name}</a>))}
    </div>
  );
}

function Lightbox({ image, onClose }) {
  useEffect(() => {
    if (!image) return undefined;
    const key = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [image, onClose]);
  if (!image) return null;
  return (
    <div className="pa-zoom" role="dialog" aria-label={image.name} onClick={onClose}>
      <img src={image.src} alt={image.name} />
      <div className="cap">{image.name}　·　點一下或按 Esc 關閉</div>
    </div>
  );
}

// 側邊欄左邊界可以拖拉調寬：寬度記在這台電腦的瀏覽器；雙擊回到原本的寬度
const WIDTH_KEY = "pa.width";

function applyWidth(px) {
  if (px) document.documentElement.style.setProperty("--pa-user", `${px}px`);
  else document.documentElement.style.removeProperty("--pa-user");
}

function savedWidth() {
  try {
    const raw = localStorage.getItem(WIDTH_KEY);
    return raw ? clampWidth(raw, window.innerWidth) : null;
  } catch {
    return null;
  }
}

function ResizeEdge() {
  const [drag, setDrag] = useState(false);
  const dragging = useRef(false);  // 拖動中每一下都要讀到最新的，不等畫面重畫
  const width = useRef(null);
  useEffect(() => {
    const fit = () => applyWidth(savedWidth());
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  const move = (event) => {
    if (!dragging.current) return;
    width.current = clampWidth(window.innerWidth - event.clientX, window.innerWidth);
    applyWidth(width.current);
  };
  const end = () => {
    if (!dragging.current) return;
    dragging.current = false;
    setDrag(false);
    document.body.classList.remove("pa-resizing");
    try { if (width.current) localStorage.setItem(WIDTH_KEY, String(width.current)); } catch { /* 私密視窗 */ }
  };
  return (
    <div className={"pa-resize" + (drag ? " on" : "")} title="拖拉調整寬度（雙擊回到原本寬度）" aria-hidden="true"
      onPointerDown={(event) => {
        event.preventDefault();
        try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* 指標已經放開 */ }
        dragging.current = true;
        setDrag(true);
        document.body.classList.add("pa-resizing");
      }}
      onPointerMove={move} onPointerUp={end} onPointerCancel={end}
      onDoubleClick={() => {
        try { localStorage.removeItem(WIDTH_KEY); } catch { /* 私密視窗 */ }
        applyWidth(null);
      }} />
  );
}

function NewConversation({ assistant, onDone }) {
  return (
    <button type="button" className="ghost" title="開一段新對話（目前這段收進紀錄）"
      onClick={async () => { if (await assistant.newConversation()) onDone(); }}>＋ 新對話</button>
  );
}

function Inline({ text }) {
  return inlineParts(text).map((part, index) => {
    if (part.kind === "strong") return <strong key={index}>{part.text}</strong>;
    if (part.kind === "code") return <code key={index}>{part.text}</code>;
    if (part.kind === "mask") return <span key={index} className="masked">{part.text}</span>;
    return <Fragment key={index}>{part.text}</Fragment>;
  });
}

function Rich({ text }) {
  return blocks(text).map((block, index) => {
    if (block.kind === "p") return <p key={index}><Inline text={block.text} /></p>;
    const Tag = block.kind;
    return <Tag key={index}>{block.items.map((item, i) => <li key={i}><Inline text={item} /></li>)}</Tag>;
  });
}

function Sources({ items, tabs, onOpenTab }) {
  if (!items.length) return null;
  return (
    <div className="sources">
      {items.map((item) => {
        const target = sourceTarget(item, tabs);
        if (target) return <button type="button" key={item} className="src" onClick={() => onOpenTab(target.key)}>↗ {item}</button>;
        return <span key={item} className="src">{isReportSource(item) ? "📊" : "📄"} {item}</span>;
      })}
    </div>
  );
}

function ProposalCard({ proposal, compact, onApply, onDismiss }) {
  const [text, setText] = useState(proposal.content || "");
  const [busy, setBusy] = useState(false);
  const display = (proposal.target && proposal.target.display) || "";
  const copy = proposalCopy(proposal);
  const actionLabel = proposal.action === "table_edit" ? "修改表格" : proposal.action;
  if (proposal.race_group_task_id && proposal.status === 'pending') return <div className="pcard">競速候選已準備，請到「代理工作」比較並選用版本。</div>;
  if (proposal.status === "applied") {
    return (
      <div className="pcard sent"><div className="h">✓ {appliedLabel(proposal)}</div>
        <div className="sentline">{actionLabel} → <b>{display}</b>　· {shortTime(proposal.decided_at)}</div></div>
    );
  }
  if (proposal.status === "dismissed") return <div className="pcard cancelled">{copy.dismissed}：{actionLabel} → {display}</div>;
  if (proposal.status === "failed") return <div className="pcard cancelled">{copy.failed}：{proposal.error || "請跟助理說要再整理一次"}</div>;
  if (compact) return <div className="pcard">{copy.compactLead}{actionLabel} → <b>{display}</b>。{copy.compactTail}</div>;
  if (proposal.action === "table_edit") return <TableProposalReview proposal={proposal} onApply={onApply} onDismiss={onDismiss} />;
  const editable = !["改狀態", "table_edit"].includes(proposal.action);
  const run = async (fn) => {
    setBusy(true);
    try { await fn(); } finally { setBusy(false); }
  };
  return (
    <div className="pcard">
      <div className="h">{copy.ask}</div>
      <div className="where">{actionLabel} → <b>{display}</b></div>
      {editable
        ? <textarea value={text} rows={4} aria-label={copy.field} onChange={(event) => setText(event.target.value)} />
        : <div className="where" style={{whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto"}}>{proposal.action === "table_edit" ? proposal.content : `改成「${proposal.content}」`}</div>}
      <div className="acts">
        <button type="button" className="btn primary" disabled={busy}
          onClick={() => run(() => onApply(proposal, editable ? text : proposal.content))}>{copy.confirm}</button>
        <button type="button" className="btn" disabled={busy} onClick={() => run(() => onDismiss(proposal))}>先不要</button>
        <span className="note">{copy.note}</span>
      </div>
    </div>
  );
}

function Message({ slug, message, proposals, tabs, compact, seconds, onOpenTab, onApply, onDismiss, onZoom }) {
  if (message.role === "user") {
    const files = message.attachments || [];
    return (
      <>
        <div className="msg-u">
          <CopyButton text={message.body || files.map((f) => f.name).join("、")} title="複製這句" />
          <div className="bubble">
            <Attachments slug={slug} items={files} onZoom={onZoom} />
            {message.body && <Inline text={message.body} />}
            {message.source_ref && <small className="message-scope">來自標註留言的交辦</small>}
            {message.request_scope && <small className="message-scope">{message.request_scope.kind === 'doc' ? `固定段落：${message.request_scope.tab_title} · ${message.request_scope.block_ids.length} 段` : `固定範圍：${message.request_scope.table_name} · ${message.request_scope.row_ids?.length} 列 · ${message.request_scope.column_ids?.length} 欄`}</small>}
          </div>
        </div>
        {(message.notes || []).map((note) => <div key={note} className="guard">🛡 {note}</div>)}
      </>
    );
  }
  if (message.role === "lead") {
    return (
      <div className="msg-a kai"><div className="who-a">負責人</div><div className="bubble"><Rich text={message.body} /></div>
        <div className="msg-meta"><CopyButton text={message.body} title="複製" /></div></div>
    );
  }
  if (message.status === "queued" || message.status === "running") {
    const working = <div className="working"><span>{messagePersona(message)} · {workingLine(message)}</span><span className="dots" /></div>;
    const live = splitSources(liveText(message)).main;
    if (!live) return working;
    const lookedLive = lookedAt(message.tools);
    return (
      <>
        <div className="msg-a writing">
          <div className="who-a">{messagePersona(message)}</div>
          {lookedLive.length > 0 && <div className="looked">查了：{lookedLive.join("、")}</div>}
          <div className="bubble"><Rich text={live} /></div>
        </div>
        {working}
      </>
    );
  }
  const { main, sources } = splitSources(message.body);
  const looked = lookedAt(message.tools);
  const download = documentUrl(slug, message);
  return (
    <>
      <div className={"msg-a" + (message.status === "failed" ? " failed" : "")}>
        <div className="who-a">{messagePersona(message)}</div>
        {looked.length > 0 && <div className="looked">查了：{looked.join("、")}</div>}
        <div className="bubble"><Rich text={main} /></div>
        {download && <a className="doc-dl" href={download} download>⬇ 下載 Word 檔</a>}
        <Sources items={sources} tabs={tabs} onOpenTab={onOpenTab} />
        {message.status === "done" && (
          <div className="msg-meta">
            <CopyButton text={message.body} title="複製回答" />
            {seconds != null && <span title="從你送出到回答寫完">{formatSeconds(seconds)}</span>}
          </div>
        )}
      </div>
      {proposals.map((p) => (
        <ProposalCard key={p.id} proposal={p} compact={compact && p.status === "pending"} onApply={onApply} onDismiss={onDismiss} />
      ))}
    </>
  );
}

function Chat({ assistant, tabs, compact, ownerName, onOpenTab, onStarter }) {
  const ref = useRef(null);
  const thread = (assistant.state && assistant.state.thread) || [];
  const proposals = (assistant.state && assistant.state.proposals) || [];
  const tail = thread.length ? thread[thread.length - 1] : null;
  const marker = tail
    ? `${tail.id}:${tail.status}:${(tail.tools || []).length}:${(tail.body || "").length}:${proposals.length}` : "";
  // 回答邊寫邊長：人停在最底才跟著捲；往上翻舊回答時不把他拉回來。新的一句一定捲到底。
  const stick = useRef(true);
  const onScroll = () => {
    const box = ref.current;
    if (box) stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  };
  const tailId = tail ? tail.id : null;
  useEffect(() => { stick.current = true; }, [tailId]);
  useEffect(() => {
    if (ref.current && stick.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [marker]);
  const [zoom, setZoom] = useState(null);
  const earlier = orphanPending(proposals, thread);
  return (
    <div className="scroll chat" ref={ref} onScroll={onScroll}>
      <Lightbox image={zoom} onClose={() => setZoom(null)} />
      {earlier.length > 0 && (
        <div className="earlier">
          <div className="earlier-t">之前的對話還有 {earlier.length} 個答案等你確認</div>
          {earlier.map((p) => <ProposalCard key={p.id} proposal={p} compact={compact} onApply={assistant.apply} onDismiss={assistant.dismiss} />)}
        </div>
      )}
      {!thread.length && (
        <>
          <div className="msg-a"><div className="who-a">✦ 專案助理</div><div className="bubble">
            <p>{ownerName}，你想完成什麼工作？我可以讀取專案裡的文件與表格，整理重點、找出缺漏，並提出修改建議。</p>
            <p>要改專案頁時，我會先整理好給你確認，你按確認才會放上去。</p>
          </div></div>
          <div className="chips">
            {STARTERS.map((s) => <button type="button" key={s} className="chip" onClick={() => onStarter(s)}>{s}</button>)}
          </div>
        </>
      )}
      {thread.map((message) => (
        <Message key={message.id} slug={assistant.slug} message={message} tabs={tabs} compact={compact} onOpenTab={onOpenTab}
          seconds={elapsedSeconds(message, thread)} onZoom={setZoom}
          proposals={proposals.filter((p) => p.message_id === message.id)} onApply={assistant.apply} onDismiss={assistant.dismiss} />
      ))}
    </div>
  );
}

let pasteCount = 0;

// 從剪貼簿貼上的圖片都叫 image.png：換成看得出來的名字
function named(file) {
  if (!file.type.startsWith("image/") || !/^image\.\w+$/i.test(file.name || "image.png")) return file;
  pasteCount += 1;
  const ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
  return new File([file], `貼上的圖片-${pasteCount}.${ext}`, { type: file.type });
}

function Composer({ assistant, value, onChange, inputRef }) {
  const busy = assistant.busyForSelectedAgent || assistant.sending;
  const agents = assistant.state?.agents || [];
  const suggestions = agentSuggestions(value, agents);
  const latestValue = useRef(value);
  latestValue.current = value;
  const picker = useRef(null);
  const [over, setOver] = useState(false);
  const files = assistant.files || [];
  const ready = files.filter((f) => f.status === "ready");
  useEffect(() => {
    const box = inputRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight, 160) + "px";
  }, [value, inputRef]);
  const submit = async () => {
    const text = value.trim();
    if ((!text && !ready.length) || busy || assistant.uploading) return;
    const result = await assistant.send(text);
    if (result && latestValue.current === value) onChange("");
  };
  const take = (list) => {
    const picked = [...(list || [])].map(named);
    if (picked.length) assistant.addFiles(picked);
  };
  return (
    <div className={"foot" + (over ? " drop" : "")}
      onDragOver={(event) => {
        if ([...(event.dataTransfer.types || [])].includes("Files")) {
          event.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOver(false); }}
      onDrop={(event) => {
        if (!event.dataTransfer.files.length) return;
        event.preventDefault();
        setOver(false);
        take(event.dataTransfer.files);
      }}>
      <AgentSelector agents={agents} value={assistant.selectedAgent} onChange={assistant.setSelectedAgent} disabled={assistant.sending} />
      {suggestions.length > 0 && <div className="agent-suggestions" aria-label="代理點名建議">{suggestions.map(agent => <button key={agent.agent_key} type="button" onClick={() => {
        assistant.setSelectedAgent(agent.agent_key); onChange(value.replace(/@[^\s@]*$/, `@${agent.agent_key} `)); inputRef.current?.focus();
      }}>{agent.icon} {agent.display_name} <small>@{agent.agent_key}</small></button>)}</div>}
      {assistant.scope && <div className="request-scope"><button type="button" aria-label="移除固定範圍" disabled={busy} onClick={() => assistant.setScope(null)}>✕</button>
        <b>{assistant.scope.table_name || "已選資料"}</b> · {assistant.scope.row_ids.length} 列 · {assistant.scope.column_ids.length} 欄
        <small>本次只修改選定範圍；切換分頁不會改變目標。</small></div>}
      {files.length > 0 && (
        <div className="att-tray">
          {files.map((f) => (
            <span key={f.key} className={"att" + (f.kind === "image" ? "" : " file") + (f.status === "uploading" ? " busy" : "")}
              title={f.status === "uploading" ? "上傳中…" : f.name}>
              {f.kind === "image"
                ? <img src={f.local || (f.attachment ? attachmentUrl(assistant.slug, f.attachment.id, "thumb") : "")} alt="" />
                : <span className="ic">{fileIcon(f.kind)}</span>}
              <span className="nm">{f.status === "uploading" ? "上傳中…" : f.name}</span>
              <button type="button" className="rm" title="拿掉" aria-label={`拿掉 ${f.name}`} onClick={() => assistant.removeFile(f.key)}>✕</button>
            </span>
          ))}
        </div>
      )}
      <div className="composer">
        <button type="button" className="attach-btn" title="附加檔案（也可以直接貼上圖片）" aria-label="附加檔案"
          disabled={files.length >= 5} onClick={() => picker.current && picker.current.click()}>{CLIP_ICON}</button>
        <input ref={picker} type="file" multiple hidden accept={ACCEPT_FILES}
          onChange={(event) => { take(event.target.files); event.target.value = ""; }} />
        <textarea ref={inputRef} rows={1} value={value} aria-label="跟專案助理說"
          placeholder={assistant.busyForSelectedAgent ? "這位代理還在回答，可以選擇另一位…" : "描述工作，也可以輸入 @ 點名代理…"}
          onChange={(event) => {
            const text = event.target.value; onChange(text);
            if (/@[a-zA-Z\u3400-\u9fff]/.test(text)) {
              try { assistant.setSelectedAgent(resolveAgentTarget(text, null, agents)); } catch { /* Keep incomplete mention as draft. */ }
            }
          }}
          onPaste={(event) => {
            const pasted = [...(event.clipboardData ? event.clipboardData.files : [])];
            if (!pasted.length) return;
            event.preventDefault();
            take(pasted);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }} />
        <button type="button" className="send" title={assistant.uploading ? "檔案還在上傳" : "送出"} aria-label="送出"
          disabled={busy || assistant.uploading || (!value.trim() && !ready.length)} onClick={submit}>↑</button>
      </div>
      <div className="hint">{attachmentHint(files, assistant.privacyMode)}</div>
    </div>
  );
}

// 「紀錄」分頁：回到目前的對話點「對話」分頁就好，這裡不再放返回鈕；按「接著這段聊」或點目前那段＝onClose 切回「對話」
function HistoryView({ assistant, tabs, compact, onOpenTab, onClose }) {
  const [list, setList] = useState(null);
  const [open, setOpen] = useState(null);
  const [zoom, setZoom] = useState(null);
  const { listConversations, loadConversation, resumeConversation } = assistant;
  useEffect(() => {
    let live = true;
    listConversations().then((found) => { if (live) setList(found || []); });
    return () => { live = false; };
  }, [listConversations]);
  const view = async (id) => {
    const found = await loadConversation(id);
    if (found) setOpen(found);
  };
  const resume = async () => {
    if (open && await resumeConversation(open.id)) onClose();
  };
  const picked = open && list ? list.find((c) => c.id === open.id) : null;
  return (
    <div className="scroll chat hist">
      <Lightbox image={zoom} onClose={() => setZoom(null)} />
      {list === null && <div className="hist-empty">讀取中…</div>}
      {list && list.filter((c) => !c.current || c.messages).length === 0 && <div className="hist-empty">還沒有以前的對話。</div>}
      {(list || []).map((c) => (
        <button type="button" key={c.id} className={"hist-item" + (c.current ? " current" : "") + (open && open.id === c.id ? " on" : "")}
          onClick={() => (c.current ? onClose() : view(c.id))}>
          <span className="d">{c.current ? "目前・" : ""}{shortTime(c.last_at || c.created_at)}</span>
          <span className="n">{c.messages} 句</span>
          <span className="q">{c.first_text || "（新對話，還沒說話）"}</span>
        </button>
      ))}
      {open && (
        <div className="hist-old">
          <div className="hist-bar">預覽：{picked ? shortTime(picked.last_at || picked.created_at) + " 的對話" : "以前的對話"}
            <button type="button" className="btn primary" onClick={resume}>接著這段聊</button></div>
          {open.messages.map((message) => (
            <Message key={message.id} slug={assistant.slug} message={message} tabs={tabs} compact onOpenTab={onOpenTab}
              seconds={elapsedSeconds(message, open.messages)} onZoom={setZoom}
              proposals={open.proposals.filter((p) => p.message_id === message.id)} onApply={assistant.apply} onDismiss={assistant.dismiss} />
          ))}
        </div>
      )}
    </div>
  );
}

function TodoList({ todo, focus, onPick, onOpenTab }) {
  const groups = todoGroups(todo);
  const on = (item) => isPicked(focus, item);
  const row = (item, label) => (
    <button type="button" key={item.rid} className={"ti" + (item.status === "已完成" ? " done" : "") + (on(item) ? " on" : "")}
      title={item.why || item.what || ""} onClick={() => onPick(item)}>
      <span className="dot">{item.status === "已完成" ? "✓" : ""}</span><span>{label}</span>
    </button>
  );
  return (
    <>
      {groups.notes.length > 0 && <h5>負責人交代的</h5>}
      {groups.notes.map((n) => <div key={"n" + n.id} className="ti kai"><span className="dot" /><span>{n.text}</span></div>)}
      <h5>待確認問題</h5>
      {groups.questions.map((q) => row(q, <><span className="n">{q.number}.</span>{clip(q.text, 24)}</>))}
      {groups.handoff.length > 0 && <h5>交接追蹤上你要交的</h5>}
      {groups.handoff.map((h) => row(h, h.text))}
      {groups.mentions.length > 0 && <h5>@ 你、還沒解決的</h5>}
      {groups.mentions.map((m) => (
        <button type="button" key={"m" + m.annotation_id} className="ti" onClick={() => onOpenTab(m.tab_key)}>
          <span className="dot" /><span>{clip(m.text, 40)}</span>
        </button>
      ))}
    </>
  );
}

function Bench({ assistant, focus, onOpenTab }) {
  const state = assistant.state || {};
  const pending = (state.proposals || []).filter((p) => p.status === "pending");
  const current = currentFocus(state.thread, focus);
  const groups = todoGroups(state.todo);
  const question = current && current.kind === "question" ? groups.questions.find((q) => q.number === current.number) : null;
  const criteria = question ? (state.criteria || {})[String(question.number)] : null;
  const handoff = current && current.kind === "handoff" ? groups.handoff.find((h) => h.rid === current.rid) : null;
  const lastDone = [...(state.thread || [])].reverse().find((m) => m.role === "assistant" && m.status === "done");
  const looked = lastDone ? lookedAt(lastDone.tools) : [];
  return (
    <>
      {pending.map((p) => <ProposalCard key={p.id} proposal={p} onApply={assistant.apply} onDismiss={assistant.dismiss} />)}
      {question && (
        <>
          <div className="qcard">
            <div className="qn">待確認問題 第 {question.number} 題　〔{question.status}〕</div>
            <div className="qt">{question.text}</div>
            {question.why && <div className="why"><b>為什麼要問：</b>{question.why}</div>}
            {criteria && criteria.use && <div className="why"><b>負責人拿答案要做什麼：</b>{criteria.use}</div>}
          </div>
          {criteria && criteria.criteria.length > 0 && (
            <>
              <div className="sec-t">答完整要有</div>
              <ul className="check">{criteria.criteria.map((c) => <li key={c}><span className="box" /><span className="t">{c}</span></li>)}</ul>
            </>
          )}
          {!pending.length && <div className="draft"><div className="wait">還在問。答完整之後，這裡會出現整理好的答案，你確認後才會放上專案頁。</div></div>}
        </>
      )}
      {handoff && (
        <div className="qcard">
          <div className="qn">交接追蹤：你要交的　〔{handoff.status}〕</div>
          <div className="qt">{handoff.text}</div>
          {handoff.what && <div className="why">{handoff.what}</div>}
          <button type="button" className="src" onClick={() => onOpenTab(handoff.tab_key)}>↗ 打開交接追蹤</button>
        </div>
      )}
      {!pending.length && !question && !handoff && (
        <>
          <div className="empty">代理整理好的修改提案會出現在這裡。先核對內容與要更新的分頁，確認後才會寫回。</div>
          <div className="sec-t">它看得到什麼</div>
          <div className="empty">{INFO(assistant.privacyMode)}</div>
        </>
      )}
      {looked.length > 0 && <><div className="sec-t">上一輪查過的</div><div className="empty">{looked.join("、")}</div></>}
    </>
  );
}

function Seg({ view, onView }) {
  return (
    <div className="seg">
      <button type="button" className={view === "chat" ? "on" : ""} onClick={() => onView("chat")}>對話</button>
      <button type="button" className={view === "manage" ? "on" : ""} onClick={() => onView("manage")}>管理</button>
    </div>
  );
}

export function AssistantSide({ assistant, me, tabs, slug, focus, draft, onDraft, inputRef, view, onView, onExpand, onClose,
  onOpenTab, onStarter, onError, onToast }) {
  const [info, setInfo] = useState(false);
  const [history, setHistory] = useState(false);
  const manager = Boolean(assistant.state && assistant.state.flags && assistant.state.flags.manager);
  const forwardsOpen = (assistant.state && assistant.state.forwards_open) || 0;
  const task = taskLine(assistant.state, focus);
  const tab = view === 'agents' ? 'agents' : paneTab(view, history);
  const pick = (key) => {
    if (key === 'agents') { setHistory(false); onView('agents'); return; }
    if (key === "manage") {
      onView("manage");
      return;
    }
    if (view === "manage" || view === 'agents') onView("chat");
    if (key === 'chat') assistant.reload();
    setHistory(key === "history");
  };
  // 10/15 負責人：上面太亂 → 標題列只留名字、ⓘ 和視窗按鈕；下面一列分頁（跟「標註」清單同一套）＋「＋ 新對話」
  return (
    <aside className="pa" aria-label="專案助理">
      <ResizeEdge />
      <div className="pa-top">
        <span className="t"><span className="spark">✦</span>專案助理</span>
        <button type="button" className={"info" + (info ? " on" : "")} title="它看得到什麼" aria-label="它看得到什麼"
          aria-expanded={info} onClick={() => setInfo(!info)}>ⓘ</button>
        <span className="grow" />
        <button type="button" className="icon-btn" title="展開成工作區" aria-label="展開成工作區" onClick={onExpand}>⤢</button>
        <button type="button" className="icon-btn x" title="收起" aria-label="收起" onClick={onClose}>✕</button>
      </div>
      <div className="pop-tabs" role="tablist" aria-label="專案助理分頁">
        {paneTabs(manager, forwardsOpen).map((t) => (
          <button type="button" key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "on" : undefined}
            title={t.count ? `有 ${t.count} 個私下問題等你回覆` : undefined} onClick={() => pick(t.key)}>
            {t.label}{t.count > 0 && <span className="n hot">{t.count}</span>}
          </button>
        ))}
        <button type="button" role="tab" aria-selected={tab === 'agents'} className={tab === 'agents' ? 'on' : undefined} onClick={() => pick('agents')}>代理工作</button>
        {view !== "manage" && view !== 'agents' && <NewConversation assistant={assistant} onDone={() => setHistory(false)} />}
      </div>
      <OrchestrationCounters counts={assistant.orchestrationCounts} onOpen={() => pick('agents')} />
      <div className={"pa-info" + (info ? " on" : "")}>{INFO(assistant.privacyMode)}</div>
      {tab === 'agents' ? <AgentBoard assistant={assistant} me={me} onOpenTarget={onOpenTab} /> : tab === "manage" ? (
        <div className="kai-side"><ManagerPanel slug={slug} onError={onError} onToast={onToast} /></div>
      ) : tab === "history" ? (
        <div className="pa-chat"><HistoryView assistant={assistant} tabs={tabs} onOpenTab={onOpenTab} onClose={() => setHistory(false)} /></div>
      ) : (
        <>
          {task && <div className="pa-task on"><span>{task}</span><button type="button" className="src" onClick={onExpand}>在工作台看</button></div>}
          <div className="pa-chat"><Chat assistant={assistant} tabs={tabs} ownerName={me.name} onOpenTab={onOpenTab} onStarter={onStarter} /></div>
          <Composer assistant={assistant} value={draft} onChange={onDraft} inputRef={inputRef} />
        </>
      )}
    </aside>
  );
}

export function AssistantWorkspace({ assistant, me, tabs, slug, focus, onFocus, draft, onDraft, inputRef, view, onView,
  onCollapse, onOpenTab, onStarter, onError, onToast }) {
  const [mtab, setMtab] = useState("chat");
  const [history, setHistory] = useState(false);
  const [help, setHelp] = useState(() => {
    try { return localStorage.getItem("pa.help") !== "min"; } catch { return true; }
  });
  const manager = Boolean(assistant.state && assistant.state.flags && assistant.state.flags.manager);
  const counts = progressCounts(assistant.state && assistant.state.todo);
  const focusNow = currentFocus(assistant.state && assistant.state.thread, focus);
  const pick = (item) => {
    const unpick = isPicked(focusNow, item);
    const next = pickTodo(focusNow, item, draft, assistant.state && assistant.state.thread);
    onFocus(next.focus);
    onDraft(next.draft);
    if (unpick) return;  // 再點一次＝取消選取，留在原地
    setHistory(false);
    setMtab("chat");
    setTimeout(() => inputRef.current && inputRef.current.focus(), 0);
  };
  const hideHelp = () => {
    setHelp(false);
    try { localStorage.setItem("pa.help", "min"); } catch { /* 私密視窗沒有 localStorage */ }
  };
  return (
    <div className="ws" aria-label="專案助理工作區">
      <div className="ws-head">
        <h1><span className="spark">✦</span>專案助理</h1>
        <OrchestrationCounters counts={assistant.orchestrationCounts} onOpen={() => onView('agents')} />
        <span className="sub">{me.name}的工作區｜陪你把專案往前推</span>
        {manager && <Seg view={view} onView={onView} />}
        <div className="pills">
          <span className="pill">待確認問題 已完成 <b>{counts.questionsDone}</b>/{counts.questions}</span>
          {counts.handoff > 0 && <span className="pill">交接追蹤 <b>{counts.handoffDone}</b>/{counts.handoff}</span>}
          {manager && (assistant.state.forwards_open || 0) > 0 && (
            <button type="button" className="pill" onClick={() => onView("manage")}>私下問題等你回覆 <b>{assistant.state.forwards_open}</b></button>
          )}
        </div>
        <button type="button" className="btn" onClick={onCollapse}><span className="lg">⤡ 收回側邊欄</span><span className="sm">← 回到專案頁</span></button>
      </div>
      {view === 'agents' ? <AgentBoard assistant={assistant} me={me} onOpenTarget={onOpenTab} /> : view === "manage" ? (
        <div className="kai-full"><ManagerPanel slug={slug} onError={onError} onToast={onToast} /></div>
      ) : (
        <>
          {help && (
            <div className="ws-help"><button type="button" onClick={hideHelp}>收起</button><b>工作區</b>：左邊是待辦（點一題就開始），
              中間是對話，右邊工作台跟著你正在做的事變。收回後回到你原本看的那一頁。</div>
          )}
          <div className="mtabs">
            {[["todo", "待辦"], ["chat", "對話"], ["bench", "工作台"]].map(([key, label]) => (
              <button type="button" key={key} className={mtab === key ? "on" : ""} onClick={() => setMtab(key)}>{label}</button>
            ))}
          </div>
          <div className="ws-grid">
            <section className={"col todo-col" + (mtab === "todo" ? " show" : "")}><h4>待辦</h4>
              <div className="scroll todo"><TodoList todo={assistant.state && assistant.state.todo} focus={focusNow} onPick={pick} onOpenTab={onOpenTab} /></div>
            </section>
            <section className={"col chat-col" + (mtab === "chat" ? " show" : "")}>
              <h4 className="tabbed">
                <button type="button" className={history ? undefined : "on"} onClick={() => setHistory(false)}>對話</button>
                <button type="button" className={history ? "on" : undefined} onClick={() => setHistory(true)}>紀錄</button>
                <span className="h4-acts"><NewConversation assistant={assistant} onDone={() => setHistory(false)} /></span>
              </h4>
              {history ? (
                <div className="pa-chat"><HistoryView assistant={assistant} tabs={tabs} onOpenTab={onOpenTab} onClose={() => setHistory(false)} /></div>
              ) : (
                <>
                  <div className="pa-chat"><Chat assistant={assistant} tabs={tabs} compact ownerName={me.name} onOpenTab={onOpenTab} onStarter={onStarter} /></div>
                  <Composer assistant={assistant} value={draft} onChange={onDraft} inputRef={inputRef} />
                </>
              )}
            </section>
            <section className={"col bench-col" + (mtab === "bench" ? " show" : "")}><h4>工作台</h4>
              <div className="scroll bench"><Bench assistant={assistant} focus={focus} onOpenTab={onOpenTab} /></div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
