import { useState } from 'react';
import { PENDING_REASON } from '../lib/labels.js';
import { formatValue } from '../lib/format.js';

function FactRow({ f, locked, onReply }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState('');
  const e = f.edit || {};
  const badge = f.status === 'EVIDENCED' ? '서류로 확인' : f.source_label;
  const save = () => {
    let v = val;
    if (e.input === 'number' || e.value_type === 'number') v = Number(val);
    else if (e.options) v = e.options.find((o) => String(o.value) === val)?.value;
    if (v === undefined || v === '' || Number.isNaN(v)) return;
    onReply({ key: f.key, kind: 'value', value: v }, `${f.label}: ${v}`);
    setEditing(false);
  };
  return (
    <li className="board-fact">
      <div>
        <span className="muted">{f.label}</span>
        <strong>{f.value_label ?? formatValue(f.value)}</strong>
        <span className={`wd-chip${f.status === 'EVIDENCED' ? ' is-evidence' : f.source_type === 'PROFILE' ? ' is-profile' : ''}`}>{badge}</span>
      </div>
      {f.editable && !locked && !editing && (
        <div className="board-actions">
          <button type="button" className="button button-link" onClick={() => setEditing(true)}>고치기</button>
          <button type="button" className="button button-link" onClick={() => onReply({ key: f.key, kind: 'retract' }, `${f.label}: 모름으로 되돌리기`)}>되돌리기</button>
        </div>
      )}
      {editing && (
        <div className="board-edit">
          {e.options ? (
            <select className="wd-input" aria-label={`${f.label} 값`} value={val} onChange={(ev) => setVal(ev.target.value)}>
              <option value="">선택</option>
              {e.options.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}
            </select>
          ) : (
            <input className="wd-input" type="number" aria-label={`${f.label} 값`} value={val} onChange={(ev) => setVal(ev.target.value)} />
          )}
          <button type="button" className="button button-small button-primary" onClick={save}>저장</button>
          <button type="button" className="button button-small button-quiet" onClick={() => setEditing(false)}>취소</button>
        </div>
      )}
    </li>
  );
}

/** 판정 보드(ui.board). 고치기·되돌리기는 onReply(quick_reply, 라벨)로 보낸다 */
export default function Board({ board, locked, onReply }) {
  const p = board.progress;
  return (
    <aside className="board wd-card" aria-label="판정 보드">
      <h3>판정 보드</h3>
      {p && <p className="muted">질문 {p.questions_asked}/{p.max_questions}</p>}
      <h4>확인된 사실</h4>
      {board.facts.length === 0 ? <p className="muted">아직 없어요</p> : (
        <ul className="plain">{board.facts.map((f) => <FactRow key={f.key} f={f} locked={locked} onReply={onReply} />)}</ul>
      )}
      <h4>확인이 필요한 항목</h4>
      {board.pending.length === 0 ? <p className="muted">없어요</p> : (
        <ul className="plain">{board.pending.map((x) => <li key={x.key}>○ {x.label} <span className="muted">({PENDING_REASON[x.reason] || x.reason})</span></li>)}</ul>
      )}
      <h4>남은 후보 {board.candidates_count}개</h4>
      <ul className="plain">{board.top_candidates.map((c, i) => <li key={i}><strong>{c.code}</strong> {c.name}</li>)}</ul>
      <h4>필요한 서류</h4>
      {board.documents_needed.length === 0 ? <p className="muted">없어요</p> : (
        <ul className="plain">{board.documents_needed.map((d) => <li key={d.evidence_type}>{d.label} <span className="muted">({d.fact_labels.join(', ')})</span></li>)}</ul>
      )}
    </aside>
  );
}
