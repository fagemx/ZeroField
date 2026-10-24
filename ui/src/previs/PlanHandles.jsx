import { useRef } from 'react';
import { useLocale } from '../i18n/react.jsx';
import { t as uiText } from '../i18n/index.js';
import { dummiesOf, keyHandles } from './blocking.js';

// The "drag" layer on the overhead plan: an amber square on the actor you are working with, light squares on the rest of the cast
// and on the camera's keys. Grab one and drag; arrow keys nudge 10 cm (Shift 1 m); Shift while dragging does not snap; Escape puts
// it back. project(x, z) gives the pixel on the plan, unproject(clientX, clientY) the stage point under the pointer.
// Dragging a key turns a preset move into a framed path, exactly as framing it in the free view does.
const NUDGE = {ArrowLeft: [1, 0], ArrowRight: [-1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]};  // the plan has the console at the top, so screen right is -x

function Handle({kind, name, label, at, mark, now, project, unproject, writable, onMove}) {
  const drag = useRef(null);
  const spot = project(at[0], at[1]);
  if (!spot) return null;
  const move = (point, event) => onMove(point, {snap: !event.shiftKey});
  return <button type="button" className={'plan-handle is-' + kind + (now ? ' is-now' : '')} style={{left: spot.x, top: spot.y}} disabled={!writable}
    aria-label={name} title={`${name} (${at[0].toFixed(1)}, ${at[1].toFixed(1)} m)`}
    onPointerDown={event => {
      if (event.button !== 0) return;
      event.preventDefault(); event.stopPropagation(); event.currentTarget.focus({preventScroll: true});
      const pointer = unproject(event.clientX, event.clientY);
      drag.current = {id: event.pointerId, offset: pointer ? [at[0] - pointer[0], at[1] - pointer[1]] : [0, 0], from: [...at]};
      try { event.currentTarget.setPointerCapture?.(event.pointerId); } catch { /* a synthetic pointer has nothing to capture */ }
    }}
    onPointerMove={event => {
      const state = drag.current;
      if (!state || state.id !== event.pointerId) return;
      const pointer = unproject(event.clientX, event.clientY);
      if (pointer) move([pointer[0] + state.offset[0], pointer[1] + state.offset[1]], event);
    }}
    onPointerUp={event => {if (drag.current?.id === event.pointerId) drag.current = null;}}
    onPointerCancel={() => {drag.current = null;}}
    onKeyDown={event => {
      if (event.key === 'Escape' && drag.current) {event.preventDefault(); event.stopPropagation(); move(drag.current.from, {shiftKey: true}); drag.current = null; return;}
      const step = NUDGE[event.key];
      if (!step || !writable) return;
      event.preventDefault();
      const size = event.shiftKey ? 1 : 0.1;
      move([at[0] + step[0] * size, at[1] + step[1] * size], {shiftKey: false});
    }}>{label && <span aria-hidden="true">{label}</span>}</button>;
}

export function PlanHandles({plan, project, unproject, writable, onDummy, onKey}) {
  useLocale();
  const keys = keyHandles(plan);
  return <div className="plan-handles">
    {dummiesOf(plan).map((dummy, index) => <Handle key={dummy.id} kind="dummy" now={dummy.id === 'actor'} name={uiText(dummy.id === 'actor' ? 'previs.dragActor' : 'previs.dragCast', {index: index})}
      label="" at={dummy.mark} project={project} unproject={unproject} writable={writable} onMove={(point, options) => onDummy(dummy.id, point, options)}/>)}
    {keys.map(key => <Handle key={'key' + key.index} kind="key" name={uiText('previs.dragKey', {index: key.index + 1})} label={'K' + (key.index + 1)}
      at={[key.position[0], key.position[2]]} project={project} unproject={unproject} writable={writable} onMove={(point, options) => onKey(key.index, point, options)}/>)}
  </div>;
}
