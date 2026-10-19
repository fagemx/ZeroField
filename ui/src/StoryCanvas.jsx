import { useEffect, useMemo, useRef, useState } from 'react';
import { applyNodeChanges, Background, Controls, Handle, MiniMap, Position, ReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useLocale } from './i18n/react.jsx';
import { t as uiText } from './i18n/index.js';
import { statusClass, statusLabel } from './format.js';
import { benchLinks } from './studioModel.js';

// Meso view: the production laid out as a story wall. Script scenes -> cast & sets -> scene shot tables ->
// each shot's media chain (keyframe -> shot, or source -> passes -> remaster). It is a view of the same
// sheet rows: edits go through the sheet's own commit/upload/run, so table, canvas and bench never diverge.
const COL = { script: 0, assets: 340, tables: 640, media: 1280 };
const MEDIA_STEP = 320, STACK_STEP = 190, SHOT_GAP = 40, ROW_H = 46;

function Media({ stage }) {
  const ref = useRef(null);
  if (stage.type === 'video') return <video ref={ref} src={stage.media.url} muted loop playsInline preload="metadata"
    onMouseEnter={() => ref.current?.play().catch(() => {})} onMouseLeave={() => ref.current?.pause()} />;
  return <img src={stage.media.url} alt="" loading="lazy" draggable={false} />;
}

function MediaNode({ data }) {
  const { stage } = data;
  return <div className={'sc-node sc-media' + (data.dim ? ' is-dim' : '')} onDoubleClick={data.onOpen} title={uiText('studio.canvasOpenHint')}>
    <Handle type="target" position={Position.Left} />
    <header><b>{data.shot}</b><span>{stage.label}</span></header>
    {stage.media ? <div className="sc-frame"><Media stage={stage} /></div>
      : <div className="sc-frame sc-empty"><span>{uiText('studio.emptyStage')}</span>{data.writable && <div className="sc-actions nodrag">
        <button disabled={data.busy} onClick={data.onUpload}>{uiText('sheetWorkspace.upload')}</button><button disabled={data.busy} onClick={data.onRun}>{uiText('studio.runStage')}</button></div>}</div>}
    <Handle type="source" position={Position.Right} />
  </div>;
}

function AssetNode({ data }) {
  return <div className={'sc-node sc-asset' + (data.dim ? ' is-dim' : '')}>
    <header><b>@{data.asset.id}</b>{data.asset.name && <span>{data.asset.name}</span>}</header>
    <div className="sc-frame">{data.asset.media ? <Media stage={{ ...data.asset, type: data.asset.type || 'image' }} /> : <span className="sc-placeholder">@{data.asset.id}</span>}</div>
    <Handle type="source" position={Position.Right} />
  </div>;
}

function ScriptNode({ data }) {
  return <div className={'sc-node sc-script' + (data.dim ? ' is-dim' : '')}>
    <header><b>{uiText('studio.canvasScript')}</b><span>{data.title}</span></header>
    <ol>{data.scenes.map(scene => <li key={scene.key}>{scene.title}<small>{uiText('story.shotCount', { count: scene.count })}</small></li>)}</ol>
    <Handle type="source" position={Position.Right} />
  </div>;
}

function SceneNode({ data }) {
  const [editing, setEditing] = useState(null), [text, setText] = useState('');
  const save = () => { if (editing && text !== editing.value) data.onCommit(editing.rid, editing.c, text); setEditing(null); };
  return <div className={'sc-node sc-scene' + (data.dim ? ' is-dim' : '')}>
    <Handle type="target" position={Position.Left} />
    <header><b>{data.title}</b><span>{uiText('story.shotCount', { count: data.rows.length })}</span></header>
    <table className="nodrag"><thead><tr><th>{data.headers[0]}</th>{data.columns.map(c => <th key={c}>{data.headers[c]}</th>)}<th>{data.statusHeader}</th></tr></thead>
      <tbody>{data.rows.map(row => <tr key={row.rid} onDoubleClick={() => data.onOpen(row.rid)}>
        <td className="sc-shot">{String(row.cells[0]?.value || '—')}</td>
        {data.columns.map(c => <td key={c} onClick={() => { if (data.writable && !data.busy) { setEditing({ rid: row.rid, c, value: String(row.cells[c]?.value || '') }); setText(String(row.cells[c]?.value || '')); } }}>
          {editing?.rid === row.rid && editing.c === c ? <textarea autoFocus aria-label={data.headers[c]} value={text} onChange={e => setText(e.target.value)} onBlur={save}
            onKeyDown={e => { if (e.key === 'Escape') setEditing(null); if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); save(); } }} />
            : <span>{String(row.cells[c]?.value || '') || '—'}</span>}</td>)}
        <td>{data.statusColumn >= 0 && row.cells[data.statusColumn]?.value ? <span className={'sc-status ' + statusClass(row.cells[data.statusColumn].value)}>{statusLabel(row.cells[data.statusColumn].value)}</span> : '—'}
          <Handle type="source" id={row.rid} position={Position.Right} /></td>
      </tr>)}</tbody></table>
  </div>;
}

const nodeTypes = { media: MediaNode, asset: AssetNode, script: ScriptNode, scene: SceneNode };

export function StoryCanvas({ storageKey, model, parsed, scenes, title, writable, busy, onOpen, onPreview, onCommit, onUpload, onRunStep }) {
  useLocale();
  const [hover, setHover] = useState(null);
  const positions = useRef(null);
  if (positions.current === null) { try { positions.current = JSON.parse(localStorage.getItem(storageKey)) || {}; } catch { positions.current = {}; } }
  const types = parsed.table.attrs.column_types || [];
  const statusColumn = model.statusColumns[0]?.index ?? -1;
  // The scene table shows the first three written columns (lens, motion, action...) next to the shot id.
  const columns = parsed.headers.map((_, c) => c).filter(c => c > 0 && c !== statusColumn && !['image', 'video', 'audio', 'status'].includes(types[c])
    && !model.cards.some(card => card.mediaChain.some(stage => stage.column === c))).slice(0, 3);
  const { nodes: built, edges } = useMemo(() => {
    const nodes = [], edges = [];
    const groups = model.sceneGroups.length ? model.sceneGroups : [{ key: '', cards: model.cards }];
    const sceneTitle = key => { const s = scenes.find(item => 'SC' + String(item.sceneIndex).padStart(2, '0') === key || item.sceneId === key); return s?.title || key || title; };
    let y = 0;
    const assetIds = [];
    for (const group of groups) {
      const rows = group.cards.map(card => card.row);
      // Each shot is laid out like a compositing bench: inputs -> stacked control passes -> stacked outputs.
      const benches = group.cards.map(card => benchLinks(card.mediaChain)), lanes = benches.map(bench => bench.lane);
      const shotSpan = lanes.map(lane => Math.max(1, lane.input.length, lane.control.length, lane.output.length) * STACK_STEP + SHOT_GAP);
      const chainHeight = shotSpan.reduce((sum, h) => sum + h, 0);
      const height = 64 + rows.length * ROW_H, span = Math.max(chainHeight, height);
      const sceneId = 'scene:' + (group.key || 'all');
      nodes.push({ id: sceneId, type: 'scene', position: { x: COL.tables, y: y + (span - height) / 2 }, data: { title: sceneTitle(group.key), rows, headers: parsed.headers, columns, statusColumn,
        statusHeader: statusColumn >= 0 ? parsed.headers[statusColumn] : '', writable, busy, onCommit, onOpen } });
      let shotY = y + (span - chainHeight) / 2;
      group.cards.forEach((card, i) => {
        const { lane, order, links } = benches[i];
        const idOf = stage => `stage:${card.row.rid}:${stage.column}`;
        order.forEach((key, k) => lane[key].forEach((stage, j) => {
          const id = idOf(stage);
          nodes.push({ id, type: 'media', position: { x: COL.media + k * MEDIA_STEP, y: shotY + j * STACK_STEP }, data: { stage, shot: card.title, writable, busy,
            onOpen: () => stage.media ? onPreview({ ...stage.media, r: card.index, c: stage.column, label: stage.label, value: stage.value }) : onOpen(card.row.rid),
            onUpload: () => onUpload(card.index, stage.column), onRun: () => onRunStep(card.row.rid, stage) } });
        }));
        // Row -> every stage of the first bench column; benchLinks wires the rest.
        if (order.length) for (const stage of lane[order[0]]) edges.push({ id: 'e:row:' + idOf(stage), source: sceneId, sourceHandle: card.row.rid, target: idOf(stage) });
        for (const [from, to] of links) edges.push({ id: `e:${idOf(from)}>${idOf(to)}`, source: idOf(from), target: idOf(to) });
        shotY += shotSpan[i];
        for (const asset of card.assets) {
          if (!assetIds.includes(asset.id)) assetIds.push(asset.id);
          const edgeId = `e:asset:${asset.id}:${sceneId}`;
          if (!edges.some(edge => edge.id === edgeId)) edges.push({ id: edgeId, source: 'asset:' + asset.id, target: sceneId });
        }
      });
      y += span + 90;
    }
    const lookup = Object.fromEntries(model.cards.flatMap(card => card.assets).map(asset => [asset.id, asset]));
    assetIds.forEach((id, i) => nodes.push({ id: 'asset:' + id, type: 'asset', position: { x: COL.assets, y: i * 200 }, data: { asset: lookup[id] } }));
    if (model.sceneGroups.length) {
      nodes.push({ id: 'script', type: 'script', position: { x: COL.script, y: 0 }, data: { title, scenes: groups.map(g => ({ key: g.key, title: sceneTitle(g.key), count: g.cards.length })) } });
      for (const group of groups) edges.push({ id: 'e:script:' + group.key, source: 'script', target: 'scene:' + (group.key || 'all') });
    }
    return { nodes: nodes.map(node => positions.current[node.id] ? { ...node, position: positions.current[node.id] } : node), edges };
  }, [model, parsed, scenes, title, writable, busy, columns.join(',')]);
  // Hovering a card traces everything that feeds it and everything it produces.
  const lit = useMemo(() => {
    if (!hover) return null;
    const seen = new Set([hover]);
    const trace = (from, to) => { const queue = [hover]; while (queue.length) { const at = queue.shift(); for (const edge of edges) if (edge[from] === at && !seen.has(edge[to])) { seen.add(edge[to]); queue.push(edge[to]); } } };
    trace('source', 'target'); trace('target', 'source');
    return seen;
  }, [hover, edges]);
  const [nodes, setNodes] = useState(built);
  useEffect(() => { setNodes(current => built.map(node => { const moved = current.find(n => n.id === node.id); return moved ? { ...node, position: moved.position } : node; })); }, [built]);
  const shown = nodes.map(node => ({ ...node, data: { ...node.data, dim: Boolean(lit && !lit.has(node.id)) } }));
  const styled = edges.map(edge => ({ ...edge, type: 'default', className: lit ? (lit.has(edge.source) && lit.has(edge.target) ? 'is-lit' : 'is-dim') : '' }));
  return <div className="story-canvas">
    <ReactFlow colorMode="dark" nodes={shown} edges={styled} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.15} maxZoom={1.6}
      nodesConnectable={false} proOptions={{ hideAttribution: true }}
      onNodesChange={changes => setNodes(current => applyNodeChanges(changes, current))}
      onNodeDragStop={(_, node) => { positions.current[node.id] = node.position; try { localStorage.setItem(storageKey, JSON.stringify(positions.current)); } catch { /* positions stay for this visit */ } }}
      onNodeMouseEnter={(_, node) => setHover(node.id)} onNodeMouseLeave={() => setHover(null)}>
      <Background gap={28} size={1} color="#1c1c1c" />
      <MiniMap position="top-right" pannable zoomable nodeColor="#2a2a2a" maskColor="rgba(0,0,0,.6)" style={{ width: 168, height: 104 }} />
      <Controls showInteractive={false} />
    </ReactFlow>
    <p className="story-canvas-hint">{uiText('studio.canvasHint')}</p>
  </div>;
}
