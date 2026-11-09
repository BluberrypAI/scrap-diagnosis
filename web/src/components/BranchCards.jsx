import { useState } from 'react';
import { CATEGORY_LABEL, EVIDENCE_REFUSE_REPLY, ROUTE_ACTION_LABEL } from '../lib/labels.js';
import { formatDateTime } from '../lib/format.js';

/** REQUEST_EVIDENCE: 서류 올리기 + 값 직접 입력(JSON, 선택) + 서류가 없어요 */
export function EvidenceCard({ docs, disabled, onUpload, onText }) {
  const [file, setFile] = useState(null);
  const [facts, setFacts] = useState('');
  const [err, setErr] = useState('');
  const submit = () => {
    let parsed = null;
    if (facts.trim()) {
      try {
        parsed = JSON.parse(facts);
      } catch {
        setErr('값 직접 입력은 JSON 형식이어야 해요. 예: {"oil_content_pct": 2}');
        return;
      }
    }
    setErr('');
    onUpload(file, parsed);
  };
  return (
    <section className="wd-card qcard" aria-label="서류 요청">
      <h3>이 서류로 확인할 수 있어요</h3>
      <ul className="plain">{docs.map((d) => <li key={d.evidence_type}><strong>{d.label}</strong> <span className="muted">확인 항목: {d.fact_labels.join(', ')}</span></li>)}</ul>
      <label className="wd-field"><span>파일 (.pdf/.txt/.md)</span>
        <input type="file" accept=".pdf,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
      <p className="muted">서류에서 읽은 값을 입력하면 &lsquo;검수 대기&rsquo;로 저장돼요. 검수가 끝난 값만 판정에 쓰여요.</p>
      <details>
        <summary>서류 값 입력</summary>
        <textarea className="wd-input" rows={2} placeholder='{"oil_content_pct": 2}' value={facts} onChange={(e) => setFacts(e.target.value)} />
      </details>
      {err && <p className="wd-alert" role="alert">{err}</p>}
      <div className="row">
        <button type="button" className="button button-primary" disabled={disabled || (!file && !facts.trim())} onClick={submit}>서류 올리기</button>
        <button type="button" className="button button-quiet" disabled={disabled} onClick={() => onText(EVIDENCE_REFUSE_REPLY)}>{EVIDENCE_REFUSE_REPLY}</button>
      </div>
    </section>
  );
}

/**
 * 검수 대기 서류 값. 업로드 값은 후보(UNVERIFIED)일 뿐이라 판정에 쓰이지 않는다.
 * onApply가 있으면(개발용) "검수 완료로 적용" 버튼을 보인다. 운영에서는 서버의 검수 흐름이 적용한다.
 * @param {{items: {doc: any, value: any}[], labels?: Record<string, string>, disabled?: boolean, onApply?: ((items: {doc: any, value: any}[]) => void)|null}} p
 */
export function PendingReview({ items, labels = {}, disabled, onApply = null }) {
  if (!items.length) return null;
  return (
    <section className="wd-card qcard" aria-label="검수 대기">
      <h3>검수 대기 <span className="muted">({items.length})</span></h3>
      <p className="muted">서류 값은 검수가 끝나야 판정에 쓰여요.</p>
      <ul className="plain">
        {items.map(({ doc, value }) => (
          <li key={value.id}>
            <strong>{labels[value.fact_key] || value.fact_key}</strong> = {typeof value.value === 'object' ? JSON.stringify(value.value) : String(value.value)}{value.unit ? ` ${value.unit}` : ''}{' '}
            <span className="muted">{doc.filename} v{value.document_version} · 검수 대기</span>
          </li>
        ))}
      </ul>
      {onApply && (
        <div className="row">
          <button type="button" className="button button-small" disabled={disabled} onClick={() => onApply(items)}>검수 완료로 적용 (개발용)</button>
        </div>
      )}
    </section>
  );
}

/** RESOLVE_CONFLICT: 서버가 준 choices를 그대로 버튼으로 */
export function ConflictCard({ conflicts, disabled, onReply, onAction }) {
  return (
    <section className="wd-card qcard" aria-label="값 확인">
      <h3>값이 서로 달라요</h3>
      {conflicts.map((c, i) => (
        <div key={i}>
          <p>
            <strong>{c.label}</strong>{' '}
            {c.claimed_label != null && <span className="muted">말씀: {c.claimed_label} · 서류: {c.evidenced_label}</span>}
          </p>
          <div className="qcard-list">
            {c.choices.map((ch, j) => (
              <button key={j} type="button" className="button button-quiet" disabled={disabled}
                onClick={() => (ch.quick_reply ? onReply(ch.quick_reply, ch.label) : onAction(ch.action, ch.key || c.fact))}>{ch.label}</button>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

/** UNSUPPORTED */
export function UnsupportedCard({ message, pending }) {
  return (
    <section className="wd-card qcard" aria-label="판정 불가">
      <h3>지금은 판정할 수 없어요</h3>
      <p>{message}</p>
      {pending.length > 0 && <ul className="plain">{pending.map((p) => <li key={p.key}>○ {p.label}</li>)}</ul>}
      <a className="button button-quiet" href="#/cases">목록으로</a>
    </section>
  );
}

const MARK = { true: '✔', false: '✗' };

/** FINAL_REVIEW(확정 전) / 인계 요약(확정 후) */
export function FinalCard({ turn, confirmed, handoff, busy, onConfirm, onRecheck }) {
  const [json, setJson] = useState(false);
  const [asking, setAsking] = useState(false); // 확정 전 화면 안 확인(네이티브 confirm은 테마·자동화 불가)
  const r = turn.ui.result;
  const v = turn.verdict;
  const guide = handoff?.route_guidance;
  return (
    <section className="wd-card qcard final" aria-label="판정 결과">
      <div className="row between">
        <h3>{r.code ? <><strong>{r.code}</strong> {r.name}</> : r.conclusion}</h3>
        <span className="wd-chip is-review">{r.review === 'UNVERIFIED' ? '검토 전 규칙 · 참고용' : r.review}</span>
      </div>
      {r.code && <p>{r.conclusion} {r.category && <span className="muted">({CATEGORY_LABEL[r.category] || r.category})</span>}</p>}
      {v.conditions.length > 0 && (
        <ul className="plain">{v.conditions.map((c, i) => <li key={i}>{MARK[c.satisfied] || '○'} {c.text}</li>)}</ul>
      )}
      {v.rationale.length > 0 && (
        <details><summary>근거 보기</summary><ul className="plain">{v.rationale.map((x, i) => (
          <li key={i}>{typeof x === 'string' ? x : <><strong>{x.ref}</strong>{x.excerpt && <> — “{x.excerpt}”</>}</>}</li>
        ))}</ul></details>
      )}
      {!confirmed && (
        <>
          <p className="muted">{r.next_step}</p>
          {!asking ? (
            <div className="row">
              <button type="button" className="button button-quiet" disabled={busy} onClick={onRecheck}>다시 확인할게요</button>
              <button type="button" className="button button-primary" disabled={busy || !turn.ui.can_confirm} onClick={() => setAsking(true)}>확정</button>
            </div>
          ) : (
            <div className="row" role="alertdialog" aria-label="확정 확인">
              <span>확정하면 판정이 기록되고 다음 단계로 넘어갑니다. 확정할까요?</span>
              <button type="button" className="button button-quiet" disabled={busy} onClick={() => setAsking(false)}>취소</button>
              <button type="button" className="button button-primary" disabled={busy} onClick={() => { setAsking(false); onConfirm(); }}>확정하기</button>
            </div>
          )}
        </>
      )}
      {confirmed && (
        <div className="handoff">
          <h4>다음 단계로 넘기는 내용</h4>
          {guide ? (
            <>
              <p><strong>{ROUTE_ACTION_LABEL[guide.action] || guide.action}</strong></p>
              <p>{guide.summary}</p>
              {guide.notes?.length > 0 && <ul className="plain">{guide.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
            </>
          ) : <p className="muted">인계 정보를 불러오지 못했어요.</p>}
          {handoff?.confirmed_at && <p className="muted">확정 {formatDateTime(handoff.confirmed_at)}</p>}
          <div className="row">
            <button type="button" className="button button-quiet" onClick={() => setJson((x) => !x)}>{json ? '인계 JSON 닫기' : '경로 추천으로 (인계 JSON)'}</button>
            <a className="button button-quiet" href="#/cases">목록으로</a>
          </div>
          {json && <pre className="json">{JSON.stringify(handoff, null, 2)}</pre>}
        </div>
      )}
    </section>
  );
}
