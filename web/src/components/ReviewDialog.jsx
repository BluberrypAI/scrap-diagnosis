import { useEffect, useMemo, useRef, useState } from 'react';
import { getCatalog } from '../api/normalize.js';
import { formatValue } from '../lib/format.js';
import { loadDocumentFile } from '../lib/docStore.js';
import { toDocumentValue } from './BranchCards.jsx';

/**
 * 서류 값 검수 창. 왼쪽에 원문, 오른쪽에 자동으로 읽은 값을 두고 하나씩 비교해 확인한다.
 *  - 원문: 이 브라우저에 보관한 파일(PDF·사진·글). 없으면 엔진이 원문에서 읽은 행 글자를 보여 준다.
 *  - 값마다 "맞아요" 또는 "고치기". 확인한 값만 판정에 쓰인다(검수 완료).
 *  - 값을 누르면 왼쪽 원문이 그 값이 있는 쪽으로 이동한다(PDF).
 *  - 좁은 화면에서는 '원문' / '읽은 값' 탭으로 바꿔 본다.
 * @param {{items: {doc: any, value: any}[], labels?: Record<string, string>, busy?: boolean,
 *   onApply: (entries: {doc: any, value: any, fixed?: any}[]) => void, onClose: () => void}} p
 */
export default function ReviewDialog({ items, labels = {}, busy, onApply, onClose }) {
  const docs = useMemo(() => {
    const m = new Map();
    for (const it of items) if (!m.has(it.doc.id)) m.set(it.doc.id, it.doc);
    return [...m.values()];
  }, [items]);
  const [docId, setDocId] = useState(docs[0]?.id);
  const doc = docs.find((d) => d.id === docId) || docs[0];
  const rows = items.filter((it) => it.doc.id === doc?.id);
  const reads = useMemo(() => readItems(doc), [doc]);
  const [marks, setMarks] = useState({}); // value_id → {state: 'ok'|'fix', mode, input}
  const [active, setActive] = useState(null); // 고른 값 id
  const [tab, setTab] = useState('values');
  const [err, setErr] = useState('');
  const box = useRef(null);
  const catalog = getCatalog();

  useEffect(() => {
    box.current?.focus();
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const activeRead = active ? reads[rows.find((r) => r.value.id === active)?.value.fact_key] : null;
  const page = activeRead?.page || 1;
  const done = items.filter((it) => marks[it.value.id]?.state).length;
  const set = (id, patch) => setMarks((m) => ({ ...m, [id]: { mode: 'eq', input: '', ...m[id], ...patch } }));

  const finish = () => {
    const out = [];
    try {
      for (const it of items) {
        const m = marks[it.value.id];
        if (!m?.state) continue;
        if (m.state === 'fix') {
          const f = catalog[it.value.fact_key] || { key: it.value.fact_key, type: 'number' };
          const v = toDocumentValue(f, { mode: m.mode, value: m.input });
          if (v === null) throw new Error(`${labels[it.value.fact_key] || it.value.fact_key}: 고칠 값을 적어 주세요`);
          out.push({ ...it, fixed: v });
        } else out.push(it);
      }
    } catch (e) {
      setErr(e.message);
      return;
    }
    setErr('');
    onApply(out);
  };

  return (
    <div className="review-overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section className="review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-title" tabIndex={-1} ref={box}>
        <header className="review-head">
          <div>
            <h2 id="review-title">서류 값 검수</h2>
            <p className="muted">원문과 읽은 값을 하나씩 비교해 주세요. 값을 누르면 원문의 그 쪽으로 이동해요. 확인한 값만 판정에 쓰여요.</p>
          </div>
          <button type="button" className="button button-quiet button-small" onClick={onClose} aria-label="검수 창 닫기">닫기</button>
        </header>
        {docs.length > 1 && (
          <div className="review-docs" role="tablist" aria-label="서류 고르기">
            {docs.map((d) => (
              <button key={d.id} type="button" role="tab" aria-selected={d.id === doc.id} className={`wd-chip${d.id === doc.id ? ' is-active' : ''}`} onClick={() => { setDocId(d.id); setActive(null); }}>
                {d.filename}
              </button>
            ))}
          </div>
        )}
        <div className="review-tabs" role="tablist" aria-label="보기 바꾸기">
          <button type="button" role="tab" aria-selected={tab === 'doc'} onClick={() => setTab('doc')}>원문</button>
          <button type="button" role="tab" aria-selected={tab === 'values'} onClick={() => setTab('values')}>읽은 값 ({rows.length})</button>
        </div>
        <div className="review-body" data-tab={tab}>
          <div className="review-pane review-doc" aria-label="원문">
            <DocumentView doc={doc} page={page} reads={reads} activeKey={rows.find((r) => r.value.id === active)?.value.fact_key} />
          </div>
          <div className="review-pane review-values" aria-label="읽은 값">
            <div className="row between review-values-head">
              <span className="muted">{rows.filter((r) => marks[r.value.id]?.state).length} / {rows.length} 확인</span>
              <button type="button" className="button button-small button-quiet" disabled={busy}
                onClick={() => rows.forEach((r) => { if (!marks[r.value.id]?.state) set(r.value.id, { state: 'ok' }); })}>
                남은 값 모두 맞아요
              </button>
            </div>
            <ul className="review-list">
              {rows.map(({ value }) => {
                const r = reads[value.fact_key];
                const m = marks[value.id] || {};
                const f = catalog[value.fact_key] || { key: value.fact_key, type: 'number' };
                const label = labels[value.fact_key] || f.label || value.fact_key;
                return (
                  <li key={value.id} className="review-item" data-state={m.state || 'todo'} data-active={active === value.id}>
                    <button type="button" className="review-item-main" onClick={() => { setActive(value.id); setTab('doc'); }} aria-label={`${label} 원문 위치 보기`}>
                      <span className="review-item-label">{label}</span>
                      <span className="review-item-value">{formatValue(value.value, value.unit ? ` ${value.unit}` : '')}</span>
                      <span className="muted small">
                        {r?.value_raw ? `원문 '${[r.value_raw, r.unit_raw].filter(Boolean).join(' ')}'` : '직접 적은 값'}
                        {r?.page ? ` · ${r.page}쪽` : ''}
                        {r?.cell_ref ? ` 표${r.cell_ref.table_index + 1} ${r.cell_ref.row + 1}행` : ''}
                      </span>
                      {r?.note && <span className="muted small">{r.note}</span>}
                    </button>
                    <div className="review-item-actions">
                      <button type="button" className={`button button-small${m.state === 'ok' ? ' button-primary' : ''}`} aria-pressed={m.state === 'ok'} disabled={busy}
                        onClick={() => set(value.id, { state: m.state === 'ok' ? null : 'ok' })}>맞아요</button>
                      <button type="button" className={`button button-small${m.state === 'fix' ? ' button-primary' : ' button-quiet'}`} aria-pressed={m.state === 'fix'} disabled={busy}
                        onClick={() => set(value.id, { state: m.state === 'fix' ? null : 'fix' })}>고치기</button>
                    </div>
                    {m.state === 'fix' && (
                      <div className="doc-value-row review-fix">
                        {f.type === 'number' ? (
                          <>
                            <select className="wd-input" aria-label={`${label} 고칠 값 모양`} value={m.mode} onChange={(e) => set(value.id, { mode: e.target.value })}>
                              <option value="eq">값</option>
                              <option value="lt">미만</option>
                            </select>
                            <input className="wd-input" inputMode="decimal" aria-label={`${label} 고칠 값`} placeholder="원문 값" value={m.input} onChange={(e) => set(value.id, { input: e.target.value })} />
                            {f.unit && <span className="muted">{f.unit}</span>}
                          </>
                        ) : (
                          <input className="wd-input" aria-label={`${label} 고칠 값`} value={m.input} onChange={(e) => set(value.id, { input: e.target.value })} />
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
        {err && <p className="wd-alert" role="alert">{err}</p>}
        <footer className="review-foot">
          <span className="muted">{done === 0 ? '값마다 맞는지 골라 주세요' : `${done}개를 판정에 반영해요. 확인하지 않은 값은 검수 대기로 남아요.`}</span>
          <div className="row">
            <button type="button" className="button button-quiet" onClick={onClose}>나중에 하기</button>
            <button type="button" className="button button-primary" disabled={busy || done === 0} onClick={finish}>검수 완료</button>
          </div>
        </footer>
      </section>
    </div>
  );
}

/** 서류의 자동 읽기 결과: {사실 키: {page, quote, cell_ref, value_raw, unit_raw, note}} */
function readItems(doc) {
  const out = {};
  for (const i of doc?.extracted_facts?.table_read?.items || []) if (!out[i.key]) out[i.key] = i;
  return out;
}

/** 원문 보기. 이 브라우저에 보관한 파일이 있으면 그대로, 없으면 원문에서 읽은 행 글자 */
function DocumentView({ doc, page, reads, activeKey }) {
  const [file, setFile] = useState(undefined); // undefined: 불러오는 중, null: 없음
  const [url, setUrl] = useState(null);
  const [text, setText] = useState(null);
  const [zoom, setZoom] = useState(false);

  useEffect(() => {
    let alive = true;
    let made = null;
    setFile(undefined);
    setText(null);
    loadDocumentFile(doc?.id, doc?.version).then(async (f) => {
      if (!alive) return;
      setFile(f);
      if (!f) return;
      made = URL.createObjectURL(f.blob);
      setUrl(made);
      if (isText(f)) setText(await f.blob.text());
    });
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [doc?.id, doc?.version]);

  if (file === undefined) return <p className="muted review-empty">원문을 불러오는 중…</p>;
  if (file && isPdf(file)) {
    // #page로 해당 쪽을 연다. key를 바꿔 쪽 이동을 확실히 반영한다
    return <iframe key={page} className="review-pdf" title={`${doc.filename} 원문`} src={`${url}#page=${page}&zoom=page-width&navpanes=0`} />;
  }
  if (file && file.type.startsWith('image/')) {
    return (
      <div className="review-image" data-zoom={zoom}>
        <button type="button" className="button button-small button-quiet review-zoom" onClick={() => setZoom((z) => !z)}>{zoom ? '화면에 맞추기' : '크게 보기'}</button>
        <img src={url} alt={`${doc.filename} 원문`} />
      </div>
    );
  }
  if (file && text !== null) return <pre className="review-text">{text}</pre>;
  // 원문이 이 브라우저에 없음: 엔진이 원문에서 읽은 행을 보여 준다
  const lines = Object.entries(reads).filter(([, r]) => r.quote);
  return (
    <div className="review-fallback">
      <p className="wd-alert is-info">이 브라우저에는 원문 파일이 없어요(다른 기기에서 올렸거나 저장소를 지웠어요). 대신 원문에서 읽은 줄을 보여 드려요. 정확히 비교하려면 성적서를 직접 펼쳐 보세요.</p>
      {lines.length ? (
        <ul className="review-quotes">
          {lines.map(([k, r]) => <li key={k} data-active={k === activeKey}><span className="muted small">{r.page}쪽</span> {r.quote}</li>)}
        </ul>
      ) : <p className="muted">읽은 줄 정보가 없어요. 직접 적은 값이면 서류를 보며 확인해 주세요.</p>}
    </div>
  );
}

const isPdf = (f) => f.type === 'application/pdf' || /\.pdf$/i.test(f.name);
const isText = (f) => f.type.startsWith('text/') || /\.(txt|csv)$/i.test(f.name);
