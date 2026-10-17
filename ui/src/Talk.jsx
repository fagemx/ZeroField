import { useEffect, useRef, useState } from "react";

import { avatarColors, initial } from "./format.js";
import { filterMembers, mentionQuery, serializeParts, splitMentions } from "./mentions.js";

export function Avatar({ id, name, size }) {
  const { bg, fg } = avatarColors(id);
  const style = { background: bg, color: fg };
  if (size) Object.assign(style, { width: size, height: size, fontSize: Math.round(size * 0.5) });
  return <span className="avatar" style={style} aria-hidden="true">{initial(name)}</span>;
}

export function MentionText({ body, members, meId }) {
  const byId = Object.fromEntries((members || []).map((m) => [m.actor_id, m]));
  return splitMentions(body).map((part, index) => (part.type === "mention"
    ? <span key={index} className={"mention" + (part.id === meId ? " me" : "")}>@{byId[part.id] ? byId[part.id].name : "（已不在名單）"}</span>
    : <span key={index}>{part.text}</span>));
}

// 留言框：contenteditable，打 @ 跳出名單，選了變成一顆名字（存的是那個人，不是字）。
// children：送出按鈕左邊的其他按鈕（解決、取消）；note：左下角的小字（例如「等 Mia 處理」）。
export function Composer({ members, me, onSend, busy, placeholder, autoFocus, note, children }) {
  const box = useRef(null);
  const [picker, setPicker] = useState(null); // {query, index}
  const [empty, setEmpty] = useState(true);
  const others = (members || []).filter((m) => m.actor_id !== me.actor_id);

  useEffect(() => {
    if (autoFocus && box.current) box.current.focus({ preventScroll: true });
  }, [autoFocus]);

  const caretText = () => {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return null;
    const range = selection.getRangeAt(0);
    if (!box.current || !box.current.contains(range.startContainer) || range.startContainer.nodeType !== 3) return null;
    return { node: range.startContainer, offset: range.startOffset, before: range.startContainer.textContent.slice(0, range.startOffset) };
  };

  const refresh = () => {
    setEmpty(!box.current || (!box.current.textContent.trim() && !box.current.querySelector(".mention")));
    const caret = caretText();
    const query = caret ? mentionQuery(caret.before) : null;
    setPicker(query === null ? null : { query, index: 0 });
  };

  const options = picker ? filterMembers(others, picker.query) : [];

  const choose = (member) => {
    const caret = caretText();
    if (!caret) return;
    const query = mentionQuery(caret.before) || "";
    const start = caret.offset - query.length - 1;
    const range = document.createRange();
    range.setStart(caret.node, Math.max(0, start));
    range.setEnd(caret.node, caret.offset);
    range.deleteContents();
    const chip = document.createElement("span");
    chip.className = "mention";
    chip.contentEditable = "false";
    chip.dataset.id = member.actor_id;
    chip.textContent = "@" + member.name;
    range.insertNode(chip);
    const space = document.createTextNode(" ");
    chip.after(space);
    const after = document.createRange();
    after.setStart(space, 1);
    after.collapse(true);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(after);
    setPicker(null);
    setEmpty(false);
  };

  const parts = () => {
    const out = [];
    const walk = (node) => {
      node.childNodes.forEach((child) => {
        if (child.nodeType === 3) out.push({ text: child.textContent });
        else if (child.dataset && child.dataset.id) out.push({ mention: child.dataset.id });
        else if (child.nodeName === "BR") out.push({ text: "\n" });
        else { walk(child); if (/^(DIV|P)$/.test(child.nodeName)) out.push({ text: "\n" }); }
      });
    };
    walk(box.current);
    return out;
  };

  const send = async () => {
    const { body } = serializeParts(parts());
    if (!body || busy) return;
    const ok = await onSend(body);
    if (ok && box.current) {
      box.current.innerHTML = "";
      setEmpty(true);
    }
  };

  return (
    <div className="reply">
      <div className="as">以 {me.name}（{me.role_label}）的身分</div>
      <div ref={box} className={"box" + (empty ? " empty" : "")} contentEditable suppressContentEditableWarning role="textbox"
        aria-multiline="true" aria-label="留言" data-ph={placeholder || "回覆。輸入 @ 可以選人通知"}
        onInput={refresh} onKeyUp={(event) => { if (!["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) refresh(); }}
        onClick={refresh}
        onPaste={(event) => { event.preventDefault(); document.execCommand("insertText", false, event.clipboardData.getData("text/plain")); }}
        onKeyDown={(event) => {
          if (picker && options.length) {
            if (event.key === "ArrowDown") { event.preventDefault(); setPicker({ ...picker, index: (picker.index + 1) % options.length }); return; }
            if (event.key === "ArrowUp") { event.preventDefault(); setPicker({ ...picker, index: (picker.index - 1 + options.length) % options.length }); return; }
            if (event.key === "Enter" || event.key === "Tab") { event.preventDefault(); choose(options[picker.index]); return; }
            if (event.key === "Escape") { event.stopPropagation(); setPicker(null); return; }
          }
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); send(); return; }
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); document.execCommand("insertLineBreak"); }
        }} />
      {picker && options.length > 0 && (
        <div className="picker" role="listbox">
          <div className="hd">選要通知的人（只能選名單上的人）</div>
          {options.map((member, index) => (
            <button type="button" key={member.actor_id} role="option" aria-selected={index === picker.index}
              className={index === picker.index ? "sel" : undefined}
              onMouseDown={(event) => { event.preventDefault(); choose(member); }}>
              <Avatar id={member.actor_id} name={member.name} size={20} />
              {member.name}<small>{member.role_label}</small>
            </button>
          ))}
        </div>
      )}
      <div className="row">
        <span className="grow">{note}</span>
        {children}
        <button type="button" className="primary" onClick={send} disabled={busy || empty}>送出</button>
      </div>
    </div>
  );
}
