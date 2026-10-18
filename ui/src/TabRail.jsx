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
    if (target && files.length !== 1) { onError("Drop one file at a time to update a page."); return; }
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
      ...(me.can_write !== false ? [{ key: "replace-file", icon: "↑", label: "Update Page from File…", disabled: importing,
        run: () => { replacementTarget.current = t; replacementInput.current?.click(); } }] : []),
      { key: "export", icon: "↓", label: `Export ${format.toUpperCase()}`, run: () => exportFile(format) },
      ...(t.surface_type === "sheet" ? [{ key: "export-new", icon: "↓", label: "Save as New Excel Workbook", run: () => exportFile("xlsx", "new_workbook") }] : []),
      ...(t.source_filename ? [{ key: "export-source", icon: "↓", label: "Download Original File", run: () => exportFile(format, "source") }] : []),
      ...(format !== "md" ? [{ key: "export-md", icon: "↓", label: "Export Markdown", run: () => exportFile("md") }] : []),
    ];
    if (!canManageTab(t, me)) return exports;
    return [
      ...exports, "sep",
      ...(admin && !t.parent_key ? [{ key: "child", icon: "＋", label: "Add a Child Page",
        run: () => { setNewSurface("doc"); setDialog({ kind: "new", parent: t.key }); } }, "sep"] : []),
      { key: "rename", icon: "✎", label: "Rename", run: () => setDialog({ kind: "rename", tab: t }) },
      { key: "up", icon: "↑", label: "Move Up", run: () => act(meta, { move: "up" }) },
      { key: "down", icon: "↓", label: "Move Down", run: () => act(meta, { move: "down" }) },
      { key: "parent", icon: "↳", label: t.parent_key ? "Move to the Top Level or Another Page" : "Move Under Another Page",
        disabled: hasChildren, note: hasChildren ? "Has Child Pages" : undefined, run: () => setDialog({ kind: "parent", tab: t }) },
      "sep",
      ...(admin ? [{ key: "history", icon: "🕘", label: "Version History…", run: () => onVersions(t.key) }] : []),
      { key: "delete", icon: "🗑", label: "Delete Page", danger: true, run: () => setDialog({ kind: "delete", tab: t }) },
      ...(admin ? ["sep", { key: "deleted", icon: "↺", label: "Deleted Pages…", note: "All Pages",
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
    <nav className="rail" aria-label={"Pages"} ref={navRef} onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }} onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); importFiles([...e.dataTransfer.files]); } }}>
      {me.can_write !== false && <><input ref={fileInput} type="file" accept=".xlsx,.docx,.md,.csv" multiple hidden onChange={(e) => { importFiles([...e.target.files]); e.target.value = ""; }} /><button className="rail-add" disabled={importing} onClick={() => fileInput.current?.click()}>{importing ? "Importing…" : "↑ Import Files"}</button><small className="rail-hint">Drop files to add pages; drop onto a page to update its revision</small></>}
      {tabs.map((t) => {
        const n = openCount(t.key);
        const can = canManageTab(t, me);
        const open = Boolean(menu && menu.key === t.key);
        const icon = SURFACE_ICON[t.surface_type] || "";
        return (
          <div key={t.key} className={"item" + (can ? " can" : "")} onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); e.stopPropagation(); importFiles([...e.dataTransfer.files], t); } }}>
            <a href={tabHash(t.key)} className={(t.parent_key ? "child " : "") + (t.key === tabKey ? "on" : "")}
              aria-current={t.key === tabKey ? "page" : undefined} title={n ? `${n}  unresolved` : undefined}
              onClick={(event) => { event.preventDefault(); closeMenu(); onNavigate(t.key); }}>
              {icon}{t.title}
              {!admin && t.created_by === me.actor_id && <span className="mine">Added by Me</span>}
              {n > 0 && <span className="n">{n}</span>}
            </a>
            {(
              <button type="button" className={"more" + (open ? " on" : "")} aria-haspopup="menu" aria-expanded={open}
                aria-label={`“${t.title}”: export and page options`} title={"Export & Page Options"}
                onClick={(event) => setMenu(open ? null : { key: t.key, rect: event.currentTarget.getBoundingClientRect() })}>⋯</button>
            )}
            {open && createPortal(
              <div ref={menuBox}>
                <Menu items={menuItems(t)} onClose={closeMenu} rect={menu.rect}
                  hint={admin ? undefined : "You and the showrunner can rename, move, and delete your pages. The showrunner can restore deleted pages."} />
              </div>,
              document.body,
            )}
          </div>
        );
      })}
      <button type="button" disabled={me.can_write === false} className="rail-add" onClick={() => { closeMenu(); setNewSurface("doc"); setDialog({ kind: "new", parent: null }); }}>
        ＋ Add Page
      </button>
    </nav>

    {/* 對話框放在清單外面：手機上清單收起來時對話框不會跟著不見 */}
      {importQueue && <ImportPreview slug={slug} files={importQueue.files} target={importQueue.target} flush={flush} onError={onError}
        onClose={() => setImportQueue(null)} onImported={(result, file, target) => {
          onTabsChanged(result.tabs); onNavigate(result.tab.key); onRenamed(result.tab.key);
          onToast(target ? "Imported a new revision and reattached annotations" : `Imported ${file.name}`);
        }} />}

      {dialog && dialog.kind === "new" && (
        <Dialog title={"Add Page"} input={{ required: true, placeholder: "Page Title" }} inputLabel={"Name"} confirmLabel={"Add"}
          message={"The new page opens immediately and is visible to the crew."}
          select={{ label: "Location", value: dialog.parent || "", options: [{ value: "", label: "Top Level (at the end)" },
            ...topLevel.map((t) => ({ value: t.key, label: `“${t.title}”` }))] }}
          onCancel={closeDialog}
          onConfirm={async ({ text, choice }) => {
            const surface_type = newSurface;
            setDialog(null);
            const result = await act(`/projects/api/${slug}/tabs`,
              { title: text, parent_key: choice || null, surface_type }, `Added “${text}”`);
            if (result && result.tab) onNavigate(result.tab.key);
          }}>
          <label className="modal-field">
            <span>Canvas Type</span>
            <select value={newSurface} onChange={(e) => setNewSurface(e.target.value)}>
              <option value="doc">Document — Write, Read &amp; Annotate</option>
              <option value="sheet">Table — Slates, Formulas &amp; Images</option>
              <option value="flow">Pipeline — Connect Tasks &amp; Agents</option>
            </select>
          </label>
        </Dialog>
      )}
      {dialog && dialog.kind === "rename" && (
        <Dialog title={"Rename Page"} input={{ required: true, value: dialog.tab.title }} inputLabel={"Name"} confirmLabel={"Rename"}
          message={"The page heading is renamed too if it still matches the old title."}
          onCancel={closeDialog}
          onConfirm={async ({ text }) => {
            setDialog(null);
            const result = await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/meta`, { title: text }, `Renamed to “${text}”`);
            if (result) onRenamed(dialog.tab.key);
          }} />
      )}
      {dialog && dialog.kind === "parent" && (
        <Dialog title={"Move To"} confirmLabel={"Move"} onCancel={closeDialog}
          select={{ label: "Location", value: dialog.tab.parent_key || "", options: [{ value: "", label: "Top Level" },
            ...topLevel.filter((t) => t.key !== dialog.tab.key).map((t) => ({ value: t.key, label: `“${t.title}”` }))] }}
          onConfirm={async ({ choice }) => {
            setDialog(null);
            await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/meta`, { parent_key: choice || null }, "Moved");
          }} />
      )}
      {dialog && dialog.kind === "delete" && (
        <Dialog title={`Delete “${dialog.tab.title}”？`} danger confirmLabel={"Delete"}
          message={`After deletion${admin ? "Restore from any page’s menu: ⋯ → Deleted Pages…" : "The showrunner can restore this page."}。`
            + (tabs.some((c) => c.parent_key === dialog.tab.key) ? "Child pages will move to the top level." : "")}
          onCancel={closeDialog}
          onConfirm={async () => {
            setDialog(null);
            const result = await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/delete`, {}, `Deleted “${dialog.tab.title}”`);
            if (result && dialog.tab.key === tabKey && result.tabs.length) onNavigate(result.tabs[0].key);
          }} />
      )}
      {dialog && dialog.kind === "deleted" && (
        <DeletedTabs slug={slug} onClose={closeDialog} onError={onError}
          onRestore={async (key, name) => {
            setDialog(null);
            await act(`/projects/api/${slug}/tabs/${key}/restore`, {}, `Restored “${name}”`);
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
    <Dialog title={"Deleted Pages"} confirmLabel={"Close"} onCancel={onClose} onConfirm={onClose}>
      {!tabs && <p className="modal-msg">Loading…</p>}
      {tabs && tabs.length === 0 && <p className="modal-msg">No deleted pages.</p>}
      {tabs && tabs.map((t) => (
        <div key={t.key} className="deleted-row">
          <span>{t.title}<small>Deleted {shortTime(t.deleted_at)}</small></span>
          <button type="button" className="ghost" onClick={() => onRestore(t.key, t.title)}>Undo</button>
        </div>
      ))}
    </Dialog>
  );
}
