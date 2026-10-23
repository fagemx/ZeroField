import React, {useEffect, useRef, useState} from 'react';
import {useTranslation} from '../i18n/react.jsx';
import {WritingBible} from './WritingBible.jsx';
import {WritingSearch} from './WritingSearch.jsx';
import {WritingFiles} from './WritingFiles.jsx';
import './writingTools.css';

const MODES = ['bible', 'search', 'files'];

// This is the sole composition entry point for AuthoringWorkspace's renderTools slot.
export function WritingToolsPanel(props) {
  const identity = `${props.slug}/${props.epId}/${props.me?.actor_id || props.me?.actorId || props.me?.id || ''}`;
  return <ToolsPanelInstance key={identity} {...props}/>;
}

function ToolsPanelInstance(props) {
  const {t} = useTranslation();
  const [mode, setMode] = useState(null);
  const [visited, setVisited] = useState([]);
  function open(next) {setMode(next);if (next) setVisited(value => value.includes(next) ? value : [...value,next]);}
  const buttons = useRef({});
  const panel = useRef(null);
  useEffect(() => {
    function shortcut(event) {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'f') {
        event.preventDefault();
        event.stopPropagation();
        open('search');
        requestAnimationFrame(() => panel.current?.querySelector('[data-writing-query]')?.focus());
      }
    }
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);
  function keyNav(event, index) {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % MODES.length;
    if (event.key === 'ArrowLeft') next = (index + MODES.length - 1) % MODES.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = MODES.length - 1;
    if (next !== undefined) { event.preventDefault(); event.stopPropagation(); buttons.current[MODES[next]]?.focus(); }
  }
  return <aside className="writing-tools" ref={panel} aria-label={t('writing.tools.title')}
    onKeyDown={event => {
      if (event.key === 'Escape' && mode) {
        event.preventDefault(); event.stopPropagation(); setMode(null); buttons.current[mode]?.focus();
      }
    }}>
    <nav className="writing-tools-nav" aria-label={t('writing.tools.title')}>
      {MODES.map((item, index) => <button key={item} type="button" ref={node => {buttons.current[item] = node;}}
        aria-expanded={mode === item} aria-controls={`writing-tools-${item}`}
        onKeyDown={event => keyNav(event, index)} onClick={() => open(mode === item ? null : item)}>
        {t(`writing.tools.${item}`)}</button>)}
    </nav>
    {/* Preserve unsent tool drafts and editor focus context across tool toggles, not identity changes. */}
    <div>
      <section id="writing-tools-bible" hidden={mode !== 'bible'} className="writing-tools-body" aria-label={t('writing.tools.bible')}>
        {/* Register and discover scoped note recovery even while the panel is collapsed. */}
        <WritingBible {...props}/>
      </section>
      <section id="writing-tools-search" hidden={mode !== 'search'} className="writing-tools-body" aria-label={t('writing.tools.search')}>
        {visited.includes('search') && <WritingSearch {...props}/>}
      </section>
      <section id="writing-tools-files" hidden={mode !== 'files'} className="writing-tools-body" aria-label={t('writing.tools.files')}>
        {visited.includes('files') && <WritingFiles {...props}/>}
      </section>
    </div>
  </aside>;
}

export default WritingToolsPanel;
