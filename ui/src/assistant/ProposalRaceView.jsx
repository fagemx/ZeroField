import { useRef, useState } from 'react';
import { Dialog } from '../Dialog.jsx';
import { proposalChanges, raceSelectionPayload } from './orchestrationModel.js';
import './orchestration.css';
import { mediaOf } from '../sheetModel.js';

const labels = { queued: '排隊中', running: '執行中', awaiting_gate: '可核對', failed: '失敗', timeout: '逾時', canceled: '已取消' };

function DiffValue({ value }) {
  const media = mediaOf(value);
  if (media?.kind === 'image') return <img className="race-image" src={media.url} alt="候選圖片" />;
  if (media) return <p><a href={media.url} download>{media.kind === 'video' ? '下載影片附件' : '下載音訊附件'}</a></p>;
  return <p>{value || '（空白）'}</p>;
}

export function ProposalRaceView({ gate, onSelect, onClose, returnFocusRef }) {
  const [busy, setBusy] = useState(null), [error, setError] = useState('');
  const requestId = useRef(crypto.randomUUID());
  const select = async proposal => {
    setBusy(proposal.id); setError('');
    try { await onSelect(raceSelectionPayload(gate, proposal.id, requestId.current)); onClose(); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };
  const candidates = gate.candidates?.length ? gate.candidates : gate.proposals.map(proposal => ({ agent_key: proposal.agent_key, status: 'awaiting_gate' }));
  return <Dialog title="比較候選版本" className="race-dialog" cancelLabel="返回看板" hideConfirm onConfirm={() => {}} onCancel={onClose} returnFocusRef={returnFocusRef}>
    <p className="race-intro">{gate.title}。選用一版後才會寫回，其他候選會略過。</p>
    {gate.stale && <p className="error" role="status">這組候選已由其他操作處理，請返回看板查看最新結果。</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="race-columns">{candidates.map(candidate => {
      const proposal = gate.proposals.find(item => item.agent_key === candidate.agent_key);
      return <article className="race-candidate" key={candidate.agent_key}>
        <header><h4>{candidate.icon || '✦'} {candidate.display_name || candidate.agent_key}</h4><small>{candidate.model || '模型未回報'} · {labels[candidate.status] || candidate.status}</small></header>
        {proposal ? <><div className="race-differences">{proposalChanges(proposal).map((group, index) => <section key={index}>
          <strong>{group.label}</strong>{group.changes.map((change, at) => <div className="race-change" key={at}>
            <small>{change.column}</small><div><span>修改前</span><DiffValue value={change.before} /></div><div className="race-after"><span>修改後</span><DiffValue value={change.after} /></div>
          </div>)}
        </section>)}</div><button type="button" className="primary" disabled={busy !== null || gate.stale} onClick={() => select(proposal)}>
          {busy === proposal.id ? '選用中…' : '✓ 選用此版'}</button></> : <p className="race-pending">{candidate.error || (['failed', 'timeout', 'canceled'].includes(candidate.status) ? '此候選未能完成。可選用其他已完成版本。' : '正在整理候選，完成後會出現在這裡。')}</p>}
      </article>;
    })}</div>
  </Dialog>;
}
