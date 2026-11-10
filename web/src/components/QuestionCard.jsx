import { useEffect, useRef, useState } from 'react';

/**
 * 질문 카드 하나. ui.question.input에 따라 모양만 다르고, 누르면 onSend(quick_reply, 라벨)을 부른다.
 *  - 선택지 버튼: {key, kind:'value', value} / {key, kind:'none_all'|'expand'|'unknown'}  (value는 kind=value일 때만)
 *  - 수치 직접 입력: {key, kind:'value', value: 숫자}
 */
export default function QuestionCard({ question: q, disabled, onSend }) {
  const [filter, setFilter] = useState('');
  const [num, setNum] = useState('');
  const title = useRef(null);
  useEffect(() => {
    title.current?.focus?.();
  }, [q.key]);

  const reply = (o) => onSend(o.kind === 'value' ? { key: q.key, kind: 'value', value: o.value } : { key: q.key, kind: o.kind }, o.label);
  const unknown = q.options.find((o) => o.kind === 'unknown') || (q.allow_unknown ? { label: q.input === 'material' ? '목록에 없어요' : '모름', kind: 'unknown' } : null);
  let opts = q.options.filter((o) => o.kind !== 'unknown');
  if (q.input === 'material' && filter.trim()) opts = opts.filter((o) => o.label.toLowerCase().includes(filter.trim().toLowerCase()));
  const sendNumber = () => {
    const v = Number(num);
    if (num.trim() === '' || Number.isNaN(v)) return;
    onSend({ key: q.key, kind: 'value', value: v }, `${v}${q.measure_unit || ''}`);
    setNum('');
  };

  return (
    <section className="wd-card qcard" aria-labelledby="qcard-title" data-input={q.input}>
      <h3 id="qcard-title" tabIndex={-1} ref={title}>{q.text}</h3>
      {q.input === 'group' && (
        <>
          {q.answered_items.length > 0 && (
            <p className="muted">이미 확인한 항목: {q.answered_items.map((a) => `${a.label}: ${a.value_label}`).join(' · ')}</p>
          )}
          <ul className="qcard-items">{q.items.map((i) => <li key={i.key}>{i.label}</li>)}</ul>
        </>
      )}
      {q.input === 'material' && (
        <input className="wd-input" placeholder="소재 검색" aria-label="소재 검색" value={filter} onChange={(e) => setFilter(e.target.value)} />
      )}
      <div className={q.input === 'material_group' ? 'qcard-grid' : 'qcard-list'}>
        {opts.map((o, i) => (
          <button key={i} type="button" className="button button-quiet" disabled={disabled} onClick={() => reply(o)}>
            {q.input === 'code' ? <><strong>{o.value}</strong> {o.label}</> : o.label}
          </button>
        ))}
        {q.input === 'material' && opts.length === 0 && <p className="muted">맞는 소재가 없어요.</p>}
      </div>
      {q.input === 'number' && q.allow_free_number && (
        <div className="qcard-number">
          <input className="wd-input" type="number" inputMode="decimal" aria-label="정확한 값" placeholder="정확한 값 입력" value={num}
            onChange={(e) => setNum(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && sendNumber()} />
          {q.measure_unit && <span>{q.measure_unit}</span>}
          <button type="button" className="button button-primary" disabled={disabled || num.trim() === ''} onClick={sendNumber}>입력</button>
        </div>
      )}
      {unknown && (
        <button type="button" className="button button-link" disabled={disabled} onClick={() => reply(unknown)}>{unknown.label}</button>
      )}
      {q.terms?.length > 0 && (
        <details>
          <summary>용어 설명</summary>
          <dl className="muted">
            {q.terms.map((t) => (
              <div key={t.term}>
                <dt><strong>{t.term}</strong></dt>
                <dd>{t.plain}{t.example ? ` (예: ${t.example})` : ''}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {q.help && (
        <details>
          <summary>어떻게 확인하나요?</summary>
          <p className="muted">{q.help}</p>
        </details>
      )}
    </section>
  );
}
