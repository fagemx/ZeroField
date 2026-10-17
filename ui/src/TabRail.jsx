import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "./api.js";
import { Dialog } from "./Dialog.jsx";
import { shortTime } from "./format.js";
import { Menu } from "./Menu.jsx";
import { canManageTab } from "./permissions.js";
import { tabHash } from "./route.js";
import { ImportPreview } from "./ImportPreview.jsx";

// 左邊的分頁清單（10/15）：最下面「＋ 新增分頁」大家都能用（滑鼠移到清單上才出現）；每一頁滑過去出現「⋯」
// 改名、移動、刪除（管理者每一頁都有，其他人只有自己新增的頁）；「已刪除的分頁…」收在管理者的「⋯」最下面。
// 以前這些藏在編輯工具列的「▤ 分頁 ▾」，只有管理者看得到。
const SURFACE_ICON = { doc: "▤ ", sheet: "▦ ", flow: "⑂ ", board: "▥ " };

export function TabRail({ slug, tabs, me, tabKey, openCount, onNavigate, onTabsChanged, flush, onRenamed, onVersions,
  onError, onToast }) {
  const admin = Boolean(me.can_edit);
  const [menu, setMenu] = useState(null); // { key, rect }
  const [dialog, setDialog] = useState(null);
  const [newSurface, setNewSurface] = useState("doc");
  const navRef = useRef(null);
  const menuBox = useRef(null);
  const fileInput = useRef(null);
  const replacementInput = useRef(null);
  const replacementTarget = useRef(null);
  const [importQueue, setImportQueue] = useState(null);
  const importing = Boolean(importQueue);
  const importFiles = async (files, target = null) => {
    if (me.can_write === false || importing || !(await flush())) return;
    if (target && files.length !== 1) { onError("更新分頁時請一次拖入一個檔案"); return; }
    if (files.length) {
      try {
        const latest = target ? await api.get(`/projects/api/${slug}/tabs/${target.key}`) : null;
        setImportQueue({ files: [...files], target: target ? structuredClone({ ...target, ...(latest.tab || latest) }) : null });
      } catch (error) { onError(error.message); }
    }
  };
  const closeMenu = useCallback(() => setMenu(null), []);
  const closeDialog = useCallback(() => setDialog(null), []);
  // 選單畫在 body 底下（左邊清單是 sticky，自成一層，畫在裡面會被內文蓋住）；點清單和選單以外的地方就關掉
  useEffect(() => {
    if (!menu) return undefined;
    const handle = (event) => {
      if ((navRef.current && navRef.current.contains(event.target)) || (menuBox.current && menuBox.current.contains(event.target))) return;
      closeMenu();
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [menu, closeMenu]);
  const topLevel = tabs.filter((t) => !t.parent_key);

  const act = async (path, body, message) => {
    if (!(await flush())) return null;
    try {
      const result = await api.post(path, body);
      if (result.tabs) onTabsChanged(result.tabs);
      if (message) onToast(message);
      return result;
    } catch (error) {
      onError(error.message);
      return null;
    }
  };

  const menuItems = (t) => {
    const hasChildren = tabs.some((c) => c.parent_key === t.key);
    const meta = `/projects/api/${slug}/tabs/${t.key}/meta`;
    const original = t.source_filename?.split(".").at(-1)?.toLowerCase();
    const format = ["xlsx", "docx", "md", "csv"].includes(original) ? original : t.surface_type === "sheet" ? "xlsx" : "docx";
    const exportFile = async (fmt, mode) => {
      if (!(await flush())) return;
      try { await api.download(`/projects/api/${slug}/tabs/${t.key}/export?format=${fmt}${mode ? `&mode=${mode}` : ""}`, mode === "source" ? t.source_filename : `${t.title}.${fmt}`); }
      catch (error) { onError(error.message); }
    };
    const exports = [
      ...(me.can_write !== false ? [{ key: "replace-file", icon: "↑", label: "從檔案更新這一頁…", disabled: importing,
        run: () => { replacementTarget.current = t; replacementInput.current?.click(); } }] : []),
      { key: "export", icon: "↓", label: `匯出 ${format.toUpperCase()}`, run: () => exportFile(format) },
      ...(t.surface_type === "sheet" ? [{ key: "export-new", icon: "↓", label: "另存新 Excel（目前資料）", run: () => exportFile("xlsx", "new_workbook") }] : []),
      ...(t.source_filename ? [{ key: "export-source", icon: "↓", label: "下載匯入時的原檔", run: () => exportFile(format, "source") }] : []),
      ...(format !== "md" ? [{ key: "export-md", icon: "↓", label: "匯出 Markdown", run: () => exportFile("md") }] : []),
    ];
    if (!canManageTab(t, me)) return exports;
    return [
      ...exports, "sep",
      ...(admin && !t.parent_key ? [{ key: "child", icon: "＋", label: "在這頁底下新增子分頁",
        run: () => { setNewSurface("doc"); setDialog({ kind: "new", parent: t.key }); } }, "sep"] : []),
      { key: "rename", icon: "✎", label: "重新命名", run: () => setDialog({ kind: "rename", tab: t }) },
      { key: "up", icon: "↑", label: "往上移", run: () => act(meta, { move: "up" }) },
      { key: "down", icon: "↓", label: "往下移", run: () => act(meta, { move: "down" }) },
      { key: "parent", icon: "↳", label: t.parent_key ? "移到第一層或別的分頁底下" : "放到別的分頁底下",
        disabled: hasChildren, note: hasChildren ? "底下有子分頁" : undefined, run: () => setDialog({ kind: "parent", tab: t }) },
      "sep",
      ...(admin ? [{ key: "history", icon: "🕘", label: "找回以前的內容…", run: () => onVersions(t.key) }] : []),
      { key: "delete", icon: "🗑", label: "刪除這一頁", danger: true, run: () => setDialog({ kind: "delete", tab: t }) },
      ...(admin ? ["sep", { key: "deleted", icon: "↺", label: "已刪除的分頁…", note: "全部的分頁",
        run: () => setDialog({ kind: "deleted" }) }] : []),
    ];
  };

  return (
    <>
    <input ref={replacementInput} type="file" accept=".xlsx,.docx,.md,.csv" hidden onChange={(event) => {
      const files = [...event.target.files];
      event.target.value = "";
      if (files.length) importFiles(files, replacementTarget.current);
    }} />
    <nav className="rail" aria-label="分頁" ref={navRef} onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }} onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); importFiles([...e.dataTransfer.files]); } }}>
      {me.can_write !== false && <><input ref={fileInput} type="file" accept=".xlsx,.docx,.md,.csv" multiple hidden onChange={(e) => { importFiles([...e.target.files]); e.target.value = ""; }} /><button className="rail-add" disabled={importing} onClick={() => fileInput.current?.click()}>{importing ? "匯入中…" : "↑ 匯入檔案"}</button><small className="rail-hint">拖入新增分頁；拖到既有分頁更新版本</small></>}
      {tabs.map((t) => {
        const n = openCount(t.key);
        const can = canManageTab(t, me);
        const open = Boolean(menu && menu.key === t.key);
        const icon = SURFACE_ICON[t.surface_type] || "";
        return (
          <div key={t.key} className={"item" + (can ? " can" : "")} onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); e.stopPropagation(); importFiles([...e.dataTransfer.files], t); } }}>
            <a href={tabHash(t.key)} className={(t.parent_key ? "child " : "") + (t.key === tabKey ? "on" : "")}
              aria-current={t.key === tabKey ? "page" : undefined} title={n ? `${n} 則還沒解決` : undefined}
              onClick={(event) => { event.preventDefault(); closeMenu(); onNavigate(t.key); }}>
              {icon}{t.title}
              {!admin && t.created_by === me.actor_id && <span className="mine">我加的</span>}
              {n > 0 && <span className="n">{n}</span>}
            </a>
            {(
              <button type="button" className={"more" + (open ? " on" : "")} aria-haspopup="menu" aria-expanded={open}
                aria-label={`「${t.title}」：匯出與分頁選項`} title="匯出與分頁選項"
                onClick={(event) => setMenu(open ? null : { key: t.key, rect: event.currentTarget.getBoundingClientRect() })}>⋯</button>
            )}
            {open && createPortal(
              <div ref={menuBox}>
                <Menu items={menuItems(t)} onClose={closeMenu} rect={menu.rect}
                  hint={admin ? undefined : "你新增的分頁，你和管理者可以改名、移動、刪除。刪掉的分頁管理者可以復原。"} />
              </div>,
              document.body,
            )}
          </div>
        );
      })}
      <button type="button" disabled={me.can_write === false} className="rail-add" onClick={() => { closeMenu(); setNewSurface("doc"); setDialog({ kind: "new", parent: null }); }}>
        ＋ 新增分頁
      </button>
    </nav>

    {/* 對話框放在清單外面：手機上清單收起來時對話框不會跟著不見 */}
      {importQueue && <ImportPreview slug={slug} files={importQueue.files} target={importQueue.target} flush={flush} onError={onError}
        onClose={() => setImportQueue(null)} onImported={(result, file, target) => {
          onTabsChanged(result.tabs); onNavigate(result.tab.key); onRenamed(result.tab.key);
          onToast(target ? "已匯入新版本並重新對位標註" : `已匯入 ${file.name}`);
        }} />}

      {dialog && dialog.kind === "new" && (
        <Dialog title="新增分頁" input={{ required: true, placeholder: "分頁名稱" }} inputLabel="名稱" confirmLabel="新增"
          message="新增後會打開這一頁，可以直接開始協作。名單上的人都看得到。"
          select={{ label: "放在", value: dialog.parent || "", options: [{ value: "", label: "第一層（排在最後）" },
            ...topLevel.map((t) => ({ value: t.key, label: `「${t.title}」底下` }))] }}
          onCancel={closeDialog}
          onConfirm={async ({ text, choice }) => {
            const surface_type = newSurface;
            setDialog(null);
            const result = await act(`/projects/api/${slug}/tabs`,
              { title: text, parent_key: choice || null, surface_type }, `已新增「${text}」`);
            if (result && result.tab) onNavigate(result.tab.key);
          }}>
          <label className="modal-field">
            <span>畫布類型</span>
            <select value={newSurface} onChange={(e) => setNewSurface(e.target.value)}>
              <option value="doc">文件 — 撰寫、閱讀與標註</option>
              <option value="sheet">表格 — 整理資料、公式與圖片</option>
              <option value="flow">工作流 — 串接任務與代理</option>
            </select>
          </label>
        </Dialog>
      )}
      {dialog && dialog.kind === "rename" && (
        <Dialog title="重新命名這一頁" input={{ required: true, value: dialog.tab.title }} inputLabel="名稱" confirmLabel="改名"
          message="頁面最上面的大標題如果還是舊名稱，會一起改。"
          onCancel={closeDialog}
          onConfirm={async ({ text }) => {
            setDialog(null);
            const result = await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/meta`, { title: text }, `已改名為「${text}」`);
            if (result) onRenamed(dialog.tab.key);
          }} />
      )}
      {dialog && dialog.kind === "parent" && (
        <Dialog title="放到哪裡" confirmLabel="移動" onCancel={closeDialog}
          select={{ label: "放在", value: dialog.tab.parent_key || "", options: [{ value: "", label: "第一層（不放在別的分頁底下）" },
            ...topLevel.filter((t) => t.key !== dialog.tab.key).map((t) => ({ value: t.key, label: `「${t.title}」底下` }))] }}
          onConfirm={async ({ choice }) => {
            setDialog(null);
            await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/meta`, { parent_key: choice || null }, "已移動");
          }} />
      )}
      {dialog && dialog.kind === "delete" && (
        <Dialog title={`刪除「${dialog.tab.title}」？`} danger confirmLabel="刪除"
          message={`刪除後${admin ? "可以從任一頁的「⋯ → 已刪除的分頁…」復原" : "管理者可以復原"}。`
            + (tabs.some((c) => c.parent_key === dialog.tab.key) ? "底下的子分頁會移到第一層。" : "")}
          onCancel={closeDialog}
          onConfirm={async () => {
            setDialog(null);
            const result = await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/delete`, {}, `已刪除「${dialog.tab.title}」`);
            if (result && dialog.tab.key === tabKey && result.tabs.length) onNavigate(result.tabs[0].key);
          }} />
      )}
      {dialog && dialog.kind === "deleted" && (
        <DeletedTabs slug={slug} onClose={closeDialog} onError={onError}
          onRestore={async (key, name) => {
            setDialog(null);
            await act(`/projects/api/${slug}/tabs/${key}/restore`, {}, `已復原「${name}」`);
          }} />
      )}
    </>
  );
}

function DeletedTabs({ slug, onClose, onRestore, onError }) {
  const [tabs, setTabs] = useState(null);
  useEffect(() => {
    api.get(`/projects/api/${slug}/deleted-tabs`).then((data) => setTabs(data.tabs)).catch((error) => { onError(error.message); onClose(); });
  }, [slug, onClose, onError]);
  return (
    <Dialog title="已刪除的分頁" confirmLabel="關閉" onCancel={onClose} onConfirm={onClose}>
      {!tabs && <p className="modal-msg">載入中…</p>}
      {tabs && tabs.length === 0 && <p className="modal-msg">沒有已刪除的分頁。</p>}
      {tabs && tabs.map((t) => (
        <div key={t.key} className="deleted-row">
          <span>{t.title}<small>刪除於 {shortTime(t.deleted_at)}</small></span>
          <button type="button" className="ghost" onClick={() => onRestore(t.key, t.title)}>復原</button>
        </div>
      ))}
    </Dialog>
  );
}
