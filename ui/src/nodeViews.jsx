import { NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { createContext, useContext } from "react";

import { FillField, StatusPill } from "./Fields.jsx";
import { shortTime } from "./format.js";

// 編輯器裡的狀態、可填格、勾選項：值不在文件裡，在 FieldsContext（伺服器的 field_value）。
// 誰都可以改值；文件本身也是大家都能改（10/15 起大家一起編輯，擋的只剩編輯鎖）。
export const FieldsContext = createContext({ values: {}, onField: async () => false });

function StatusView({ node }) {
  const { values, onField } = useContext(FieldsContext);
  const info = values[node.attrs.fid] || null;
  return (
    <NodeViewWrapper as="span" className="pd-inline" data-interactive="">
      <StatusPill value={info ? info.value : node.attrs.label} info={info}
        onChange={(value) => onField(node.attrs.fid, value)} />
    </NodeViewWrapper>
  );
}

function FillView({ node }) {
  const { values, onField } = useContext(FieldsContext);
  const info = values[node.attrs.fid] || null;
  return (
    <NodeViewWrapper as="span" className="pd-inline pd-fill" data-interactive="">
      <FillField value={info ? info.value : ""} info={info} onSave={(value) => onField(node.attrs.fid, value)} />
    </NodeViewWrapper>
  );
}

function TaskItemView({ node }) {
  const { values, onField } = useContext(FieldsContext);
  const info = values[node.attrs.fid] || null;
  const checked = info ? info.value === "true" : Boolean(node.attrs.checked);
  return (
    <NodeViewWrapper as="div" className="task-row" data-checked={checked ? "true" : "false"}>
      <label contentEditable={false} data-interactive="" suppressContentEditableWarning>
        <input type="checkbox" checked={checked} aria-label={"Select"}
          title={info && info.by_name ? `${info.by_name}・${shortTime(info.at)}` : "Select to save"}
          onMouseDown={(event) => event.stopPropagation()}
          onChange={() => node.attrs.fid && onField(node.attrs.fid, checked ? "false" : "true")} />
      </label>
      <NodeViewContent as="div" className="task-text" />
    </NodeViewWrapper>
  );
}

const insideControl = ({ event }) => Boolean(
  event && event.target && event.target.closest && event.target.closest("[data-interactive]"),
);

export const statusNodeView = ReactNodeViewRenderer(StatusView, { as: "span", stopEvent: insideControl });
export const fillNodeView = ReactNodeViewRenderer(FillView, { as: "span", stopEvent: insideControl });
export const taskItemNodeView = ReactNodeViewRenderer(TaskItemView, { as: "li", stopEvent: insideControl });
