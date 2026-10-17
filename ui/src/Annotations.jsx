// 標註的畫面：卡片、右邊欄（寬螢幕放卡片、窄一點放小圓點）、手機下方卡片、右上的標註清單、標記檢視選單。
// 規則（誰該處理、誰能解決）在 rules.js；這裡只負責畫。
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { activityLine, shortTime } from "./format.js";
import {
  LABELS, canDelete, canResolve, chipFor, comments, isOpen, isRecordOnly, latestAt, panelGroups, todoFor, waitingOn,
} from "./rules.js";
import { Avatar, Composer, MentionText } from "./Talk.jsx";

export const PANEL_RULE = "待我處理：有人 @ 你、你還沒回覆也還沒解決的；你確認過的字被改了也會在這裡。"
  + "標了「問題」「要修改」卻沒 @ 人的，交給管理者。";

export function hasCard(a, adding) {
  return a.kind === "row" || Boolean(a.label) || comments(a).length > 0 || Boolean(a.draft) || adding.has(a.id);
}

function Who({ actor, members }) {
  const member = (members || []).find((m) => m.actor_id === actor.actor_id);
  return (
    <>
      <b>{actor.name}</b>
      {member && <span className="role">{member.role_label}</span>}
    </>
  );
}

function Chips({ a, rowLabel }) {
  const chip = chipFor(a);
  return (
    <div className="hd">
      {(a.reconfirm || a.label) && <span className={"chip " + chip.cls}>{chip.text}</span>}
      {a.kind === "row" && <span className="chip row">整列｜{rowLabel || "這一列"}</span>}
      {a.orphaned_at && <span className="chip orphan">原文已修改</span>}
    </div>
  );
}

// 一則標註的卡片。focused：展開（看得到原文、回覆框、按鈕）。
export function AnnotationCard({ a, focused, me, members, rowLabel, busy, adding, onAct }) {
  const isAdmin = me.role === "admin";
  if (isRecordOnly(a) && !adding.has(a.id)) {
    return (
      <div className={"card compact" + (focused ? " focus" : "")} data-ann={a.id}>
        <span className="chip lb-ok">✓ 已確認</span>
        <Avatar id={a.label_by || a.created_by} name={a.created_by_name} size={18} />
        <b>{nameOf(members, a.label_by || a.created_by, a.created_by_name)}</b>
        <span className="t">{shortTime(a.label_at || a.created_at)}</span>
        {focused && (
          <span className="acts-inline">
            <button type="button" className="linkish" data-act="add-note">加說明</button>
            {canDelete(a, me.actor_id, isAdmin) && <button type="button" className="linkish danger" data-act="remove">取消確認</button>}
          </span>
        )}
      </div>
    );
  }
  const real = comments(a);
  const wait = isOpen(a) ? waitingOn(a, members) : [];
  const placeholder = a.draft ? "寫下補充說明。輸入 @ 可以選人通知"
    : (real.length || a.kind === "row" ? "回覆。輸入 @ 可以選人通知" : "要補充說明嗎？可以不填。輸入 @ 可以選人通知");
  return (
    <div className={"card" + (focused ? " focus" : "")} data-ann={a.id}>
      <Chips a={a} rowLabel={rowLabel} />
      {(focused || a.orphaned_at) && a.kind === "text" && <div className="quote">「{a.anchor.quote}」</div>}
      {a.reconfirm && (
        <div className="reconfirm">
          {nameOf(members, a.label_by, "")} 確認過的字被改了：「{a.reconfirm.from}」→「{a.reconfirm.to}」
          {focused && <><br /><button type="button" className="ghost ok" data-act="reconfirm">✓ 再確認一次</button></>}
        </div>
      )}
      {!a.reconfirm && a.moved && (
        <div className="moved">內文改過，這則已跟著移到新的文字：「{a.moved.from}」→「{a.moved.to}」</div>
      )}
      {!real.length && !a.draft && a.kind === "text" && (
        <div className="msg">
          <Avatar id={a.created_by} name={a.created_by_name} size={22} />
          <div className="b">
            <div className="who"><Who actor={{ actor_id: a.created_by, name: a.created_by_name }} members={members} />
              <span className="t">{shortTime(a.created_at)}</span></div>
            <div className="text">{a.label ? `標了「${LABELS[a.label].name}」` : (a.style === "ul" ? "劃線" : "螢光筆")}</div>
          </div>
        </div>
      )}
      {(a.messages || []).map((m) => (m.kind === "comment" ? (
        <div className="msg" key={m.id}>
          <Avatar id={m.actor.actor_id} name={m.actor.name} size={22} />
          <div className="b">
            <div className="who">
              <Who actor={m.actor} members={members} /><span className="t">{shortTime(m.at)}</span>
              {focused && m.actor.actor_id === me.actor_id && (
                <button type="button" className="linkish del" data-act="del-comment" data-comment={m.id}>刪除</button>
              )}
            </div>
            <div className="text"><MentionText body={m.body} members={members} meId={me.actor_id} /></div>
          </div>
        </div>
      ) : (
        <div className="sysline" key={m.id}>{activityLine(m)} · {shortTime(m.at)}</div>
      )))}
      {a.resolved_at ? (
        <div className="resolved-line">
          ✓ {nameOf(members, a.resolved_by, "")} 已解決 · {shortTime(a.resolved_at)}
          {focused && <button type="button" className="linkish" data-act="reopen">重新打開</button>}
        </div>
      ) : focused ? (
        <>
          <Composer members={members} me={me} busy={busy} autoFocus={Boolean(a.draft || adding.has(a.id))}
            placeholder={placeholder} note={wait.length ? `等 ${wait.join("、")} 處理` : ""}
            onSend={(body) => onAct(a, "send", { body })}>
            {a.draft
              ? <button type="button" className="ghost" data-act="cancel">取消</button>
              : (isOpen(a) && !a.reconfirm && canResolve(a, me.actor_id, isAdmin)
                ? <button type="button" className="ghost ok" data-act="resolve">✓ 解決</button> : null)}
          </Composer>
          {!a.draft && a.kind === "text" && canDelete(a, me.actor_id, isAdmin) && (
            <div className="remove-line"><button type="button" className="linkish danger" data-act="remove">刪除這則標註</button></div>
          )}
        </>
      ) : (wait.length > 0 && <div className="t wait">等 {wait.join("、")} 處理</div>)}
    </div>
  );
}

function nameOf(members, id, fallback) {
  const member = (members || []).find((m) => m.actor_id === id);
  return member ? member.name : (fallback || "（已不在名單）");
}

function bubbleText(a) {
  const n = comments(a).length;
  if (a.reconfirm) return "?";
  if (a.label === "ok" && !n) return "✓";
  return String(n || "!");
}

function bubbleClass(a) {
  if (a.reconfirm) return "re";
  if (a.label) return LABELS[a.label].cls;
  if (a.kind === "row") return "row";
  return "nt";
}

// 右邊欄。items：[{a, want}]（want＝這則在內文上的高度，相對內文頂端），已經照 want 排好。
// mode：wide＝卡片排在右邊；slim＝小圓點，點了卡片浮出來。
export function Margin({ mode, items, focusId, orphans, minHeight, cardProps, onBubble, onCardClick, onOrphans }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root || mode !== "wide") return;
    const cards = items.map((it) => ({ it, el: root.querySelector(`.card[data-ann="${it.a.id}"]`) })).filter((x) => x.el);
    const GAP = 8;
    const index = cards.findIndex((x) => x.it.a.id === focusId);
    const tops = cards.map((x) => x.it.want);
    if (index < 0) {
      let y = -Infinity;
      cards.forEach((x, i) => { tops[i] = Math.max(x.it.want, y); y = tops[i] + x.el.offsetHeight + GAP; });
    } else {
      tops[index] = cards[index].it.want;
      let y = tops[index] - GAP;
      for (let i = index - 1; i >= 0; i -= 1) { tops[i] = Math.min(cards[i].it.want, y - cards[i].el.offsetHeight); y = tops[i] - GAP; }
      y = tops[index] + cards[index].el.offsetHeight + GAP;
      for (let i = index + 1; i < cards.length; i += 1) { tops[i] = Math.max(cards[i].it.want, y); y = tops[i] + cards[i].el.offsetHeight + GAP; }
    }
    cards.forEach((x, i) => { x.el.style.top = `${Math.round(tops[i])}px`; });
  });

  if (mode === "wide") {
    return (
      <aside className="margin" ref={ref} style={{ minHeight }} onClick={onCardClick}>
        {orphans > 0 && (
          <div className="orphan-note">{orphans} 則標註找不到原文
            <button type="button" className="linkish" onClick={onOrphans}>查看</button></div>
        )}
        {items.map((it) => (
          <AnnotationCard key={it.a.id} a={it.a} focused={it.a.id === focusId} rowLabel={it.rowLabel} {...cardProps} />
        ))}
      </aside>
    );
  }
  let y = -Infinity;
  const focused = items.find((it) => it.a.id === focusId);
  return (
    <aside className="margin" style={{ minHeight }} onClick={onCardClick}>
      {items.map((it) => {
        const top = Math.max(it.want, y);
        y = top + 30;
        const n = comments(it.a).length;
        return (
          <button type="button" key={it.a.id} className={"bub " + bubbleClass(it.a) + (it.a.id === focusId ? " on" : "")}
            style={{ top }} title={(it.a.reconfirm ? "要重新確認" : it.a.label ? LABELS[it.a.label].name : "對話") + (n ? `｜${n} 則` : "")}
            onClick={(event) => { event.stopPropagation(); onBubble(it.a.id); }}>
            {bubbleText(it.a)}
          </button>
        );
      })}
      {orphans > 0 && (
        <button type="button" className="bub orph" title={`${orphans} 則標註找不到原文`} onClick={onOrphans}>!{orphans}</button>
      )}
      {focused && (
        <div className="float-wrap" style={{ top: Math.max(-20, focused.want - 6) }}>
          <AnnotationCard a={focused.a} focused rowLabel={focused.rowLabel} {...cardProps} />
        </div>
      )}
    </aside>
  );
}

// 手機：卡片從下面拉上來
export function Sheet({ item, tabTitle, cardProps, onClose, onCardClick }) {
  if (!item) return null;
  return (
    <div className="sheet on" onClick={onCardClick}>
      <div className="close"><span>{tabTitle}</span><button type="button" className="linkish" onClick={onClose}>關閉</button></div>
      <AnnotationCard a={item.a} focused rowLabel={item.rowLabel} {...cardProps} />
    </div>
  );
}

// 右上「標註」清單
export function AnnotationPanel({ open, annotations, me, members, tabs, rowLabels, section, onSection, onPick, onReattach, onResolve, onClose }) {
  const ref = useRef(null);
  const [tab, setTab] = useState("todo");
  const [mineOnly, setMineOnly] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const isAdmin = me.role === "admin";

  useEffect(() => {
    if (section === "orphan" || section === "all") setTab("all");
    else if (section === "todo") setTab("todo");
  }, [section]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (ref.current && !ref.current.contains(event.target) && !event.target.closest("#annBtn")) onClose();
    };
    const esc = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open, onClose]);

  useEffect(() => {
    if (!open || section !== "orphan" || !ref.current) return;
    const target = ref.current.querySelector('.sec[data-sec="orphan"]');
    if (target) target.scrollIntoView({ block: "start" });
    onSection(null);
  }, [open, section, onSection]);

  if (!open) return null;
  const groups = panelGroups(annotations, me.actor_id, isAdmin, mineOnly);
  const titleOf = (key) => (tabs.find((t) => t.key === key) || {}).title || "";

  const item = (a) => {
    const last = comments(a).slice(-1)[0];
    const chip = chipFor(a);
    const quote = a.kind === "row" ? (rowLabels[a.id] || "這一列") : a.anchor.quote;
    const who = last ? last.actor : { actor_id: a.created_by, name: a.created_by_name };
    let line;
    if (a.reconfirm) line = `確認過的字被改成「${a.reconfirm.to}」`;
    else if (last) line = <MentionText body={last.body} members={members} meId={me.actor_id} />;
    else if (a.label) line = `標了「${LABELS[a.label].name}」`;
    else line = (a.messages || []).length ? activityLine(a.messages[a.messages.length - 1]) : "";
    return (
      <div key={a.id} className={"item" + (a.resolved_at ? " done" : "")} role="button" tabIndex={0}
        onClick={(event) => { if (!event.target.closest("[data-act]")) onPick(a); }}
        onKeyDown={(event) => { if (event.key === "Enter") onPick(a); }}>
        <div className="r1">
          <span className={"chip " + chip.cls}>{chip.text}</span>
          {a.orphaned_at && <span className="chip orphan">原文已修改</span>}
          <span className="where">{titleOf(a.tab_key)}</span>
          <span className="t">{shortTime(latestAt(a))}</span>
        </div>
        <div className="q">{quote}</div>
        <div className="last"><Avatar id={who.actor_id} name={who.name} size={16} /><b>{who.name}</b><span>{line}</span></div>
        {a.orphaned_at && !a.resolved_at && (
          <div className="acts">
            {a.kind === "text" && (isAdmin || a.created_by === me.actor_id) && (
              <button type="button" className="ghost xs" data-act="reattach" onClick={() => onReattach(a)}>重新選位置</button>
            )}
            {canResolve(a, me.actor_id, isAdmin) && (
              <button type="button" className="ghost xs" data-act="resolve" onClick={() => onResolve(a)}>解決</button>
            )}
          </div>
        )}
      </div>
    );
  };

  const sectionBlock = (key, title, list, fold) => (list.length ? (
    <div className="sec" data-sec={key} key={key}>
      {fold ? (
        <button type="button" className={"sec-hd fold" + (showDone ? " open" : "")} onClick={() => setShowDone(!showDone)}>
          {title}<span className="n">{list.length}</span><span className="chev">›</span>
        </button>
      ) : <div className="sec-hd">{title}<span className="n">{list.length}</span></div>}
      {(!fold || showDone) && list.map(item)}
    </div>
  ) : null);

  const all = groups.open.length + groups.orphan.length + groups.done.length;
  let body;
  if (tab === "todo") {
    body = groups.todo.length ? groups.todo.map(item) : <div className="empty">目前沒有等你處理的標註</div>;
  } else {
    body = all ? [
      sectionBlock("open", "未解決", groups.open),
      sectionBlock("orphan", "原文已修改", groups.orphan),
      sectionBlock("done", "已解決", groups.done, true),
    ] : <div className="empty">還沒有標註</div>;
  }
  return (
    <div className="pop on" ref={ref} role="dialog" aria-label="標註清單">
      <div className="pop-hd">
        <b>標註</b>
        <label className="switch">
          <input type="checkbox" checked={mineOnly} onChange={(event) => setMineOnly(event.target.checked)} /><i />只看我提出的
        </label>
      </div>
      <div className="pop-tabs">
        <button type="button" className={tab === "todo" ? "on" : undefined} onClick={() => setTab("todo")}>
          待我處理{groups.todo.length > 0 && <span className="n hot">{groups.todo.length}</span>}
        </button>
        <button type="button" className={tab === "all" ? "on" : undefined} onClick={() => setTab("all")}>
          全部<span className="n">{all}</span>
        </button>
        <span className="info" tabIndex={0} data-tip={PANEL_RULE} aria-label={PANEL_RULE}>ⓘ</span>
      </div>
      <div className="pop-list">{body}</div>
    </div>
  );
}

export function todoCount(annotations, me) {
  return annotations.filter((a) => todoFor(a, me.actor_id, me.role === "admin")).length;
}

// 標記檢視：只影響自己的畫面
export function ViewMenu({ open, rect, view, showResolved, onView, onResolved, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => { if (ref.current && !ref.current.contains(event.target) && !event.target.closest("#viewBtn")) onClose(); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, onClose]);
  if (!open || !rect) return null;
  const option = (value, label) => (
    <button type="button" onClick={() => { onView(value); onClose(); }}>{label}{view === value && <span className="tick">✓</span>}</button>
  );
  return (
    <div className="menu on view-menu" ref={ref} style={{ top: rect.bottom + 4, left: Math.max(8, Math.min(rect.left, window.innerWidth - 268)) }}>
      {option("all", "大家的螢光筆和劃線")}
      {option("mine", "只看我自己的")}
      {option("none", "不顯示螢光筆和劃線")}
      <button type="button" onClick={() => { onResolved(!showResolved); onClose(); }}>顯示已解決的標註{showResolved && <span className="tick">✓</span>}</button>
      <div className="note">只影響你自己看到的畫面。「問題」「要修改」「已確認」和有說明的標註一律都會顯示。</div>
    </div>
  );
}

export const VIEW_LABEL = { all: "標記：大家的", mine: "標記：只有我的", none: "標記：不顯示" };

export function PenIcon() {
  return (
    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14.5 4.5l5 5L11 18H6v-5z" /><path d="M4 21h9" /></svg>
  );
}

export function NoteIcon() {
  return (
    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8.5L6 19.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" /><path d="M8.5 9.5h7M8.5 12.5h4" />
    </svg>
  );
}

export function LinkIcon() {
  return (
    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" /><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" />
    </svg>
  );
}
