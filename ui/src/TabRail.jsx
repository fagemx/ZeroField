import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "./api.js";
import { Dialog } from "./Dialog.jsx";
import { shortTime } from "./format.js";
import { Menu } from "./Menu.jsx";
import { canManageTab } from "./permissions.js";
import { tabHash } from "./route.js";
import { ImportPreview } from "./ImportPreview.jsx";
import { Icon } from "./Icon.jsx";

// 左邊的分頁清單（10/15）：最下面「＋ 新增分頁」大家都能用（滑鼠移到清單上才出現）；每一頁滑過去出現「⋯」
// 改名、移動、刪除（管理者每一頁都有，其他人只有自己新增的頁）；「已刪除的分頁…」收在管理者的「⋯」最下面。
// 以前這些藏在編輯工具列的「▤ 分頁 ▾」，只有管理者看得到。
const SURFACE_ICON = { doc: "doc", sheet: "table", flow: "flow", board: "board" };

export function TabRail({ slug, tabs, me, tabKey, openCount, onNavigate, onTabsChanged, flush, onRenamed, onVersions,
  onError, onToast }) {
  const locale = useLocale();
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
    if (target && files.length !== 1) { onError(uiText("tabRail.dropOneFileAtATimeToUpdateA")); return; }
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
      ...(me.can_write !== false ? [{ key: "replace-file", icon: "↑", label: uiText("tabRail.updatePageFromFile"), disabled: importing,
        run: () => { replacementTarget.current = t; replacementInput.current?.click(); } }] : []),
      { key: "export", icon: "↓", label: uiText("tabRail.export", {v0: (format.toUpperCase())}), run: () => exportFile(format) },
      ...(t.surface_type === "sheet" ? [{ key: "export-new", icon: "↓", label: uiText("tabRail.saveAsNewExcelWorkbook"), run: () => exportFile("xlsx", "new_workbook") }] : []),
      ...(t.source_filename ? [{ key: "export-source", icon: "↓", label: uiText("tabRail.downloadOriginalFile"), run: () => exportFile(format, "source") }] : []),
      ...(format !== "md" ? [{ key: "export-md", icon: "↓", label: uiText("tabRail.exportMarkdown"), run: () => exportFile("md") }] : []),
    ];
    if (!canManageTab(t, me)) return exports;
    return [
      ...exports, "sep",
      ...(admin && !t.parent_key ? [{ key: "child", icon: "＋", label: uiText("tabRail.addAChildPage"),
        run: () => { setNewSurface("doc"); setDialog({ kind: "new", parent: t.key }); } }, "sep"] : []),
      { key: "rename", icon: <Icon name="pencil" />, label: uiText("tabRail.rename"), run: () => setDialog({ kind: "rename", tab: t }) },
      { key: "up", icon: "↑", label: uiText("tabRail.moveUp"), run: () => act(meta, { move: "up" }) },
      { key: "down", icon: "↓", label: uiText("tabRail.moveDown"), run: () => act(meta, { move: "down" }) },
      { key: "parent", icon: "↳", label: t.parent_key ? uiText("tabRail.moveToTheTopLevelOrAnotherPage") : uiText("tabRail.moveUnderAnotherPage"),
        disabled: hasChildren, note: hasChildren ? uiText("tabRail.hasChildPages") : undefined, run: () => setDialog({ kind: "parent", tab: t }) },
      "sep",
      ...(admin ? [{ key: "history", icon: <Icon name="history" />, label: uiText("tabRail.versionHistory"), run: () => onVersions(t.key) }] : []),
      { key: "delete", icon: <Icon name="trash" />, label: uiText("tabRail.deletePage"), danger: true, run: () => setDialog({ kind: "delete", tab: t }) },
      ...(admin ? ["sep", { key: "deleted", icon: "↺", label: uiText("tabRail.deletedPages"), note: uiText("tabRail.allPages"),
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
    <nav className="rail" aria-label={uiText("tabRail.pages")} ref={navRef} onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }} onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); importFiles([...e.dataTransfer.files]); } }}>
      {me.can_write !== false && <><input ref={fileInput} type="file" accept=".xlsx,.docx,.md,.csv" multiple hidden onChange={(e) => { importFiles([...e.target.files]); e.target.value = ""; }} /><button className="rail-add" disabled={importing} onClick={() => fileInput.current?.click()}>{importing ? uiText("tabRail.importing") : uiText("tabRail.importFiles")}</button><small className="rail-hint">{uiText("tabRail.dropFilesToAddPagesDropOntoAPage")}</small></>}
      {tabs.map((t) => {
        const n = openCount(t.key);
        const can = canManageTab(t, me);
        const open = Boolean(menu && menu.key === t.key);
        const icon = SURFACE_ICON[t.surface_type] ? <Icon name={SURFACE_ICON[t.surface_type]} /> : null;
        return (
          <div key={t.key} className={"item" + (can ? " can" : "")} onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); e.stopPropagation(); importFiles([...e.dataTransfer.files], t); } }}>
            <a href={tabHash(t.key)} className={(t.parent_key ? "child " : "") + (t.key === tabKey ? "on" : "")}
              aria-current={t.key === tabKey ? "page" : undefined} title={n ? uiText("tabRail.unresolved", {v0: (n)}) : undefined}
              onClick={(event) => { event.preventDefault(); closeMenu(); onNavigate(t.key); }}>
              {icon}{t.title}
              {!admin && t.created_by === me.actor_id && <span className="mine">{uiText("tabRail.addedByMe")}</span>}
              {n > 0 && <span className="n">{n}</span>}
            </a>
            {(
              <button type="button" className={"more" + (open ? " on" : "")} aria-haspopup="menu" aria-expanded={open}
                aria-label={uiText("tabRail.exportAndPageOptions", {v0: (t.title)})} title={uiText("tabRail.exportPageOptions")}
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
      <button type="button" disabled={me.can_write === false} className="rail-add" onClick={() => { closeMenu(); setNewSurface("doc"); setDialog({ kind: "new", parent: null }); }}>{uiText("tabRail.addPage")}</button>
    </nav>

    {/* 對話框放在清單外面：手機上清單收起來時對話框不會跟著不見 */}
      {importQueue && <ImportPreview slug={slug} files={importQueue.files} target={importQueue.target} flush={flush} onError={onError}
        onClose={() => setImportQueue(null)} onImported={(result, file, target) => {
          onTabsChanged(result.tabs); onNavigate(result.tab.key); onRenamed(result.tab.key);
          onToast(target ? "Imported a new revision and reattached annotations" : `Imported ${file.name}`);
        }} />}

      {dialog && dialog.kind === "new" && (
        <Dialog title={uiText("tabRail.addPage2")} input={{ required: true, placeholder: uiText('common.dialogPageTitle') }} inputLabel={uiText("common.inputName")} confirmLabel={uiText("tabRail.add")}
          message={uiText("tabRail.newPageExplanation")}
          select={{ label: uiText('common.dialogLocation'), value: dialog.parent || "", options: [{ value: "", label: uiText('common.dialogTopLevelAtTheEnd') },
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
            <span>{uiText("tabRail.canvasType")}</span>
            <select value={newSurface} onChange={(e) => setNewSurface(e.target.value)}>
              <option value="doc">{uiText("tabRail.documentWriteReadAnnotate")}</option>
              <option value="sheet">{uiText("tabRail.tableSlatesFormulasImages")}</option>
              <option value="flow">{uiText("tabRail.pipelineConnectTasksAgents")}</option>
            </select>
          </label>
        </Dialog>
      )}
      {dialog && dialog.kind === "rename" && (
        <Dialog title={uiText("tabRail.renamePage")} input={{ required: true, value: dialog.tab.title }} inputLabel={uiText("common.inputName")} confirmLabel={uiText("tabRail.rename")}
          message={uiText("tabRail.renameExplanation")}
          onCancel={closeDialog}
          onConfirm={async ({ text }) => {
            setDialog(null);
            const result = await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/meta`, { title: text }, `Renamed to “${text}”`);
            if (result) onRenamed(dialog.tab.key);
          }} />
      )}
      {dialog && dialog.kind === "parent" && (
        <Dialog title={uiText("tabRail.moveTo")} confirmLabel={uiText("tabRail.move")} onCancel={closeDialog}
          select={{ label: uiText('common.dialogLocation'), value: dialog.tab.parent_key || "", options: [{ value: "", label: uiText('common.dialogTopLevel') },
            ...topLevel.filter((t) => t.key !== dialog.tab.key).map((t) => ({ value: t.key, label: `“${t.title}”` }))] }}
          onConfirm={async ({ choice }) => {
            setDialog(null);
            await act(`/projects/api/${slug}/tabs/${dialog.tab.key}/meta`, { parent_key: choice || null }, "Moved");
          }} />
      )}
      {dialog && dialog.kind === "delete" && (
        <Dialog title={uiText("tabRail.delete", {v0: (dialog.tab.title)})} danger confirmLabel={uiText("tabRail.delete")}
          message={uiText("tabRail.afterDeletion", {v0: (admin ? "Restore from any page’s menu: ⋯ → Deleted Pages…" : "The showrunner can restore this page.")})
            + (tabs.some((c) => c.parent_key === dialog.tab.key) ? uiText("tabRail.childPagesMove") : "")}
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
  const locale = useLocale();
  const [tabs, setTabs] = useState(null);
  useEffect(() => {
    api.get(`/projects/api/${slug}/deleted-tabs`).then((data) => setTabs(data.tabs)).catch((error) => { onError(error.message); onClose(); });
  }, [slug, onClose, onError]);
  return (
    <Dialog title={uiText("tabRail.deletedPages2")} confirmLabel={uiText("tabRail.close")} onCancel={onClose} onConfirm={onClose}>
      {!tabs && <p className="modal-msg">{uiText("tabRail.loading")}</p>}
      {tabs && tabs.length === 0 && <p className="modal-msg">{uiText("tabRail.noDeletedPages")}</p>}
      {tabs && tabs.map((t) => (
        <div key={t.key} className="deleted-row">
          <span>{t.title}<small>{uiText("tabRail.deleted", {v0: (shortTime(t.deleted_at))})}</small></span>
          <button type="button" className="ghost" onClick={() => onRestore(t.key, t.title)}>{uiText("tabRail.undo")}</button>
        </div>
      ))}
    </Dialog>
  );
}
