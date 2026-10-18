import { roleLabel } from './format.js';
import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
// 標註的畫面：卡片、右邊欄（寬螢幕放卡片、窄一點放小圓點）、手機下方卡片、右上的標註清單、標記檢視選單。
// 規則（誰該處理、誰能解決）在 rules.js；這裡只負責畫。
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { activityLine, shortTime } from "./format.js";
import {
  LABELS, canDelete, canResolve, chipFor, comments, isOpen, isRecordOnly, latestAt, panelGroups, todoFor, waitingOn,
} from "./rules.js";
import { Avatar, Composer, MentionText } from "./Talk.jsx";

export const PANEL_RULE = () => uiText("annotations.needsYouIncludesMentionsAwaitingYourReplyAndChanges") + " " + uiText("annotations.unassignedQuestionsAndRevisionRequestsGoToTheShowrunner");

export function hasCard(a, adding) {
  return a.kind === "row" || Boolean(a.label) || comments(a).length > 0 || Boolean(a.draft) || adding.has(a.id);
}

function Who({ actor, members }) {
  const locale = useLocale();
  const member = (members || []).find((m) => m.actor_id === actor.actor_id);
  return (
    <>
      <b>{actor.name}</b>
      {member && <span className="role">{roleLabel(member.role, member.role_label)}</span>}
    </>
  );
}

function Chips({ a, rowLabel }) {
  const locale = useLocale();
  const chip = chipFor(a);
  return (
    <div className="hd">
      {(a.reconfirm || a.label) && <span className={"chip " + chip.cls}>{chip.text}</span>}
      {a.kind === "row" && <span className="chip row">{uiText("annotations.row", {v0: (rowLabel || uiText("annotations.thisRow"))})}</span>}
      {a.orphaned_at && <span className="chip orphan">{uiText("annotations.sourceChanged")}</span>}
    </div>
  );
}

// 一則標註的卡片。focused：展開（看得到原文、回覆框、按鈕）。
export function AnnotationCard({ a, focused, me, members, agents, rowLabel, busy, adding, onAct }) {
  const locale = useLocale();
  const isAdmin = me.role === "admin";
  if (isRecordOnly(a) && !adding.has(a.id)) {
    return (
      <div className={"card compact" + (focused ? " focus" : "")} data-ann={a.id}>
        <span className="chip lb-ok">{uiText("annotations.approved")}</span>
        <Avatar id={a.label_by || a.created_by} name={a.created_by_name} size={18} />
        <b>{nameOf(members, a.label_by || a.created_by, a.created_by_name)}</b>
        <span className="t">{shortTime(a.label_at || a.created_at)}</span>
        {focused && (
          <span className="acts-inline">
            <button type="button" className="linkish" data-act="add-note">{uiText("annotations.addNote")}</button>
            {canDelete(a, me.actor_id, isAdmin) && <button type="button" className="linkish danger" data-act="remove">{uiText("annotations.removeApproval")}</button>}
          </span>
        )}
      </div>
    );
  }
  const real = comments(a);
  const wait = isOpen(a) ? waitingOn(a, members) : [];
  const placeholder = a.draft ? uiText("annotations.addANoteTypeToNotifyACrewMember")
    : (real.length || a.kind === "row" ? uiText("annotations.replyTypeToNotifyACrewMember") : uiText("annotations.optionalNoteTypeToNotifyACrewMember"));
  return (
    <div className={"card" + (focused ? " focus" : "")} data-ann={a.id}>
      <Chips a={a} rowLabel={rowLabel} />
      {(focused || a.orphaned_at) && a.kind === "text" && <div className="quote">“{a.anchor.quote}”</div>}
      {a.reconfirm && (
        <div className="reconfirm">{uiText("annotations.approvedTextWasChanged", {v0: (nameOf(members, a.label_by, "")), v1: (a.reconfirm.from), v2: (a.reconfirm.to)})}{focused && <><br /><button type="button" className="ghost ok" data-act="reconfirm">{uiText("annotations.approveAgain")}</button></>}
        </div>
      )}
      {!a.reconfirm && a.moved && (
        <div className="moved">{uiText("annotations.thisNoteMovedWithTheRevisedText", {v0: (a.moved.from), v1: (a.moved.to)})}</div>
      )}
      {!real.length && !a.draft && a.kind === "text" && (
        <div className="msg">
          <Avatar id={a.created_by} name={a.created_by_name} size={22} />
          <div className="b">
            <div className="who"><Who actor={{ actor_id: a.created_by, name: a.created_by_name }} members={members} />
              <span className="t">{shortTime(a.created_at)}</span></div>
            <div className="text">{a.label ? uiText("annotations.marked", {v0: (LABELS[a.label].name)}) : (a.style === "ul" ? uiText("annotations.underline") : uiText("annotations.highlight"))}</div>
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
                <button type="button" className="linkish del" data-act="del-comment" data-comment={m.id}>{uiText("annotations.delete")}</button>
              )}
            </div>
            <div className="text"><MentionText body={m.body} members={members} meId={me.actor_id} /></div>
          </div>
        </div>
      ) : (
        <div className="sysline" key={m.id}>{activityLine(m)} · {shortTime(m.at)}</div>
      )))}
      {a.resolved_at ? (
        <div className="resolved-line">{uiText("annotations.resolved", {v0: (nameOf(members, a.resolved_by, "")), v1: (shortTime(a.resolved_at))})}{focused && <button type="button" className="linkish" data-act="reopen">{uiText("annotations.reopen")}</button>}
        </div>
      ) : focused ? (
        <>
          <Composer members={members} agents={agents} me={me} busy={busy} autoFocus={Boolean(a.draft || adding.has(a.id))}
            initialText={a.initialText || ''}
            placeholder={placeholder} note={wait.length ? `Waiting for ${wait.join("、")}  to respond` : ""}
            onSend={(body) => onAct(a, "send", { body })}>
            {a.draft
              ? <button type="button" className="ghost" data-act="cancel">{uiText("annotations.cancel")}</button>
              : (isOpen(a) && !a.reconfirm && canResolve(a, me.actor_id, isAdmin)
                ? <button type="button" className="ghost ok" data-act="resolve">{uiText("annotations.resolve")}</button> : null)}
          </Composer>
          {!a.draft && a.kind === "text" && canDelete(a, me.actor_id, isAdmin) && (
            <div className="remove-line"><button type="button" className="linkish danger" data-act="remove">{uiText("annotations.deleteAnnotation")}</button></div>
          )}
        </>
      ) : (wait.length > 0 && <div className="t wait">{uiText("annotations.waitingForToRespond", {v0: (wait.join("、"))})}</div>)}
    </div>
  );
}

function nameOf(members, id, fallback) {
  const member = (members || []).find((m) => m.actor_id === id);
  return member ? member.name : (fallback || uiText("annotations.noLongerOnTheCrew"));
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
  const locale = useLocale();
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
          <div className="orphan-note">{uiText("annotations.annotationsHaveNoMatchingSource", {v0: (orphans)})}<button type="button" className="linkish" onClick={onOrphans}>{uiText("annotations.view")}</button></div>
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
            style={{ top }} title={(it.a.reconfirm ? uiText("annotations.approvalRequiredAgain") : it.a.label ? LABELS[it.a.label].name : uiText("annotations.conversation")) + (n ? uiText("annotations.items", {v0: (n)}) : "")}
            onClick={(event) => { event.stopPropagation(); onBubble(it.a.id); }}>
            {bubbleText(it.a)}
          </button>
        );
      })}
      {orphans > 0 && (
        <button type="button" className="bub orph" title={uiText("annotations.annotationsHaveNoMatchingSource", {v0: (orphans)})} onClick={onOrphans}>!{orphans}</button>
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
  const locale = useLocale();
  if (!item) return null;
  return (
    <div className="sheet on" onClick={onCardClick}>
      <div className="close"><span>{tabTitle}</span><button type="button" className="linkish" onClick={onClose}>{uiText("annotations.close")}</button></div>
      <AnnotationCard a={item.a} focused rowLabel={item.rowLabel} {...cardProps} />
    </div>
  );
}

// 右上「標註」清單
export function AnnotationPanel({ open, annotations, me, members, tabs, rowLabels, section, onSection, onPick, onReattach, onResolve, onClose }) {
  const locale = useLocale();
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
    const quote = a.kind === "row" ? (rowLabels[a.id] || uiText("annotations.thisRow")) : a.anchor.quote;
    const who = last ? last.actor : { actor_id: a.created_by, name: a.created_by_name };
    let line;
    if (a.reconfirm) line = uiText("annotations.approvedTextChangedTo", {v0: (a.reconfirm.to)});
    else if (last) line = <MentionText body={last.body} members={members} meId={me.actor_id} />;
    else if (a.label) line = uiText("annotations.marked", {v0: (LABELS[a.label].name)});
    else line = (a.messages || []).length ? activityLine(a.messages[a.messages.length - 1]) : "";
    return (
      <div key={a.id} className={"item" + (a.resolved_at ? " done" : "")} role="button" tabIndex={0}
        onClick={(event) => { if (!event.target.closest("[data-act]")) onPick(a); }}
        onKeyDown={(event) => { if (event.key === "Enter") onPick(a); }}>
        <div className="r1">
          <span className={"chip " + chip.cls}>{chip.text}</span>
          {a.orphaned_at && <span className="chip orphan">{uiText("annotations.sourceChanged")}</span>}
          <span className="where">{titleOf(a.tab_key)}</span>
          <span className="t">{shortTime(latestAt(a))}</span>
        </div>
        <div className="q">{quote}</div>
        <div className="last"><Avatar id={who.actor_id} name={who.name} size={16} /><b>{who.name}</b><span>{line}</span></div>
        {a.orphaned_at && !a.resolved_at && (
          <div className="acts">
            {a.kind === "text" && (isAdmin || a.created_by === me.actor_id) && (
              <button type="button" className="ghost xs" data-act="reattach" onClick={() => onReattach(a)}>{uiText("annotations.reattach")}</button>
            )}
            {canResolve(a, me.actor_id, isAdmin) && (
              <button type="button" className="ghost xs" data-act="resolve" onClick={() => onResolve(a)}>{uiText("annotations.resolve2")}</button>
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
    body = groups.todo.length ? groups.todo.map(item) : <div className="empty">{uiText("annotations.noAnnotationsNeedYourAttention")}</div>;
  } else {
    body = all ? [
      sectionBlock("open", uiText("annotations.open"), groups.open),
      sectionBlock("orphan", uiText("annotations.sourceChanged"), groups.orphan),
      sectionBlock("done", uiText("annotations.resolved2"), groups.done, true),
    ] : <div className="empty">{uiText("annotations.noAnnotationsYet")}</div>;
  }
  return (
    <div className="pop on" ref={ref} role="dialog" aria-label={uiText("annotations.annotations")}>
      <div className="pop-hd">
        <b>{uiText("annotations.annotations")}</b>
        <label className="switch">
          <input type="checkbox" checked={mineOnly} onChange={(event) => setMineOnly(event.target.checked)} /><i />{uiText("annotations.onlyMine")}</label>
      </div>
      <div className="pop-tabs">
        <button type="button" className={tab === "todo" ? "on" : undefined} onClick={() => setTab("todo")}>{uiText("annotations.needsYou")}{groups.todo.length > 0 && <span className="n hot">{groups.todo.length}</span>}
        </button>
        <button type="button" className={tab === "all" ? "on" : undefined} onClick={() => setTab("all")}>{uiText("annotations.all")}<span className="n">{all}</span>
        </button>
        <span className="info" tabIndex={0} data-tip={PANEL_RULE()} aria-label={PANEL_RULE()}>ⓘ</span>
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
  const locale = useLocale();
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
      {option("all", uiText("annotations.showAllHighlightsAndUnderlines"))}
      {option("mine", uiText("annotations.showOnlyMine"))}
      {option("none", uiText("annotations.hideHighlightsAndUnderlines"))}
      <button type="button" onClick={() => { onResolved(!showResolved); onClose(); }}>{uiText("annotations.showResolvedAnnotations")}{showResolved && <span className="tick">✓</span>}</button>
      <div className="note">{uiText("annotations.thisChangesYourViewOnlyQuestionsRevisionRequestsApprovals")}</div>
    </div>
  );
}

export const VIEW_LABEL = { get all() { return uiText("annotations.markupAll"); }, get mine() { return uiText("annotations.markupMine"); }, get none() { return uiText("annotations.markupHidden"); } };

export function PenIcon() {
  const locale = useLocale();
  return (
    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14.5 4.5l5 5L11 18H6v-5z" /><path d="M4 21h9" /></svg>
  );
}

export function NoteIcon() {
  const locale = useLocale();
  return (
    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8.5L6 19.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" /><path d="M8.5 9.5h7M8.5 12.5h4" />
    </svg>
  );
}

export function LinkIcon() {
  const locale = useLocale();
  return (
    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" /><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" />
    </svg>
  );
}
