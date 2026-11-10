import { useState } from 'react';
import { api } from '../api/index.js';
import { useLoad } from '../lib/useLoad.js';

function Json({ value }) {
  let text = value;
  if (typeof value !== 'string') text = JSON.stringify(value, null, 2);
  else {
    try {
      text = JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      /* 그대로 */
    }
  }
  return <pre className="dev-json">{text}</pre>;
}

function LlmCall({ c }) {
  return (
    <div className="dev-call">
      <div className="row between">
        <strong>{c.name === 'extract' ? '① 추출 AI' : c.name === 'respond' ? '② 응답 AI' : c.name}</strong>
        <span className="muted small">{c.model} · {c.prompt_version} · {c.latency_ms}ms{c.error ? ` · 오류: ${c.error}` : ''}</span>
      </div>
      <details><summary>지침(system)</summary><pre className="dev-json">{c.system}</pre></details>
      <details open><summary>AI에 보낸 데이터(user, 식별 정보 가림)</summary>{c.user ? <Json value={c.user} /> : <p className="muted">기록 안 함(해시 {c.user_sha256?.slice(0, 12)}, {c.user_len}자)</p>}</details>
      <details open><summary>AI가 돌려준 값(parsed)</summary>{c.parsed ? <Json value={c.parsed} /> : <p className="muted">없음</p>}</details>
    </div>
  );
}

const INTENT = { why: '왜 묻나·왜 이 결과인가', term: '뜻·해당 여부·확인 방법', off_topic: '문진 밖 요청' };

/** 보충 설명용으로 엔진이 찾은 자료와, AI가 그중 인용한 것·최종 설명 */
function FoundMaterial({ t }) {
  const r = t.responder || {};
  const f = r.assist_found;
  const a = t.response?.assist;
  if (!f) return null;
  const cited = new Set(r.assist_cited_ids || []);
  const mark = (id) => (cited.has(id) ? <span className="dev-badge">AI 인용</span> : null);
  return (
    <div className="dev-found">
      <p>
        <strong>사용자 질문:</strong> {f.user_question || '-'} <span className="muted small">({INTENT[f.intent] || f.intent})</span>
      </p>
      <p className="small">
        준비된 자료로 답함: <strong>{r.assist_matched ? '예' : '아니오(자료 보강 대상)'}</strong> · 웹 검색: <strong>{r.assist_web ? '사용' : '안 함'}</strong> · 설명 문장: <strong>{r.assist_used_template ? '템플릿(AI 문장이 검사에 걸림)' : 'AI 작성'}</strong>
      </p>
      {f.best_faq && (
        <div className="dev-found-block"><h5>가장 가까운 FAQ</h5><p className="small"><strong>Q.</strong> {f.best_faq.q}<br /><strong>A.</strong> {f.best_faq.a}</p></div>
      )}
      {f.guide?.length > 0 && (
        <div className="dev-found-block">
          <h5>질문 안내 {f.guide.length}건</h5>
          {f.guide.map((g, i) => (
            <details key={i}>
              <summary>{g.label}: {g.what}</summary>
              {g.why && <p className="small"><strong>왜:</strong> {g.why}</p>}
              {g.options && <ul className="small">{g.options.map((o, k) => <li key={k}><strong>{o.label}</strong>: {o.means}</li>)}</ul>}
              {g.faq?.length > 0 && <ul className="small">{g.faq.map((q, k) => <li key={k}>Q. {q.q} → {q.a}</li>)}</ul>}
            </details>
          ))}
        </div>
      )}
      {f.topics?.length > 0 && (
        <div className="dev-found-block"><h5>참고 주제</h5><ul className="small">{f.topics.map((tp, i) => <li key={i}><strong>{tp.topic}</strong>: {tp.plain}</li>)}</ul></div>
      )}
      {f.terms?.length > 0 && (
        <div className="dev-found-block"><h5>용어집</h5><ul className="small">{f.terms.map((x, i) => <li key={i}><strong>{x.term}</strong>: {x.plain}</li>)}</ul></div>
      )}
      {f.rules?.length > 0 && (
        <div className="dev-found-block"><h5>관련 규칙</h5><ul className="small">{f.rules.map((x, i) => <li key={i}>{x.plain || '(설명 없음)'} <span className="muted">[{(x.basis_ids || []).join(', ')}]</span></li>)}</ul></div>
      )}
      {f.sources?.length > 0 && (
        <div className="dev-found-block">
          <h5>근거 {f.sources.length}건</h5>
          <ul className="small">
            {f.sources.map((s) => (
              <li key={s.id}>
                <code>{s.id}</code> {s.type === 'WEB' ? '[웹 검색] ' : ''}{s.ref}{s.url && <> — <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a></>} {mark(s.id)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {f.option_effects && Object.keys(f.option_effects).length > 0 && (
        <div className="dev-found-block"><h5>답에 따라 남는 후보 수</h5><p className="small">{Object.entries(f.option_effects).map(([k, v]) => `${k}: ${v}개`).join(' · ')}</p></div>
      )}
      {a && <div className="dev-found-block"><h5>최종 설명(사용자에게 보인 문장)</h5><p className="small">{a.text}</p></div>}
    </div>
  );
}

/** 개발자용: 턴마다 AI에 보낸 데이터·받은 값·검사 결과·엔진 판단(Trace 기반) */
export default function DevTracePage({ id }) {
  const { data: trace, error } = useLoad(() => api.trace(id), [id]);
  const [mode, setMode] = useState('all');
  if (error) return <p className="wd-alert" role="alert">{error.message}</p>;
  if (!trace) return <p className="muted">불러오는 중…</p>;
  const turns = trace.sessions.flatMap((s) => s.turns.filter((t) => t.kind === 'TURN'));
  const shown = mode === 'found' ? turns.filter((r) => r.payload.responder?.assist_found) : turns;

  return (
    <div className="dev-page">
      <div className="row between">
        <h2>AI 데이터 확인 (개발자용)</h2>
        <a className="button button-small button-quiet" href={`#/cases/${id}`}>← 문진으로</a>
      </div>
      <div className="row rg-tabs">
        <button type="button" className={`button button-small ${mode === 'all' ? 'button-primary' : 'button-quiet'}`} onClick={() => setMode('all')}>전체 메시지</button>
        <button type="button" className={`button button-small ${mode === 'found' ? 'button-primary' : 'button-quiet'}`} onClick={() => setMode('found')}>안내용으로 찾은 자료만</button>
      </div>
      <p className="muted small">
        {mode === 'all'
          ? '턴마다 AI에 보낸 데이터와 받은 값, guard 검사, 엔진이 고른 분기와 질문 점수를 보여 줍니다. 판정은 엔진 규칙만 정합니다.'
          : '사용자가 "왜?", "뭐예요?"라고 물은 턴만 모았습니다. 엔진이 찾은 자료(질문 안내·FAQ·용어집·규칙 근거·웹 검색)와 AI가 그중 인용한 것, 최종 설명 문장을 보여 줍니다.'}
      </p>
      {shown.length === 0 && <p className="muted">{mode === 'found' ? '보충 설명을 한 턴이 아직 없어요. 문진 중에 "왜 물어봐요?", "PCB가 뭐예요?"처럼 물어보세요.' : '아직 기록된 턴이 없어요.'}</p>}
      {shown.map((row) => {
        const t = row.payload;
        const ex = t.extraction;
        const n = turns.indexOf(row) + 1;
        if (mode === 'found') {
          return (
            <section key={row.seq} className="wd-card dev-turn">
              <h3>턴 {n} <span className="muted small">{row.turn_id}</span></h3>
              <FoundMaterial t={t} />
            </section>
          );
        }
        return (
          <section key={row.seq} className="wd-card dev-turn">
            <h3>턴 {n} · {t.branch} <span className="muted small">{row.turn_id}</span></h3>
            <p><strong>입력:</strong> {t.input_text || (t.quick_reply ? `버튼 ${JSON.stringify(t.quick_reply)}` : '(없음)')}</p>
            {(t.llm_calls || []).map((c, k) => <LlmCall key={k} c={c} />)}
            {ex && (
              <details open>
                <summary>guard 검사 결과(엔진에 들어간 사실 / 버린 값)</summary>
                <Json value={{ 채택: (ex.facts || []).map((f) => ({ key: f.key, value: f.value, status: f.status })), 묶음답: ex.group_answer, 사용자질문: ex.user_question, 질문종류: ex.question_kind, 버림: ex.rejected, 막힘: ex.llm_blocked }} />
              </details>
            )}
            <details>
              <summary>엔진 판단: 분기 이유·질문 점수</summary>
              <p className="small">{t.branch_reason}</p>
              <Json value={(t.score_breakdown || []).slice(0, 5).map((e) => ({ 질문: e.key, 점수: e.score, 정보량: e.gain, 비용: e.cost, 답별_남는후보: e.outcomes }))} />
            </details>
            {t.responder?.assist_found && (
              <details>
                <summary>안내용으로 찾은 자료</summary>
                <FoundMaterial t={t} />
              </details>
            )}
            <details>
              <summary>응답 검사</summary>
              <Json value={{ 템플릿: t.responder?.used_template, 문제: t.responder?.problems }} />
            </details>
            <details>
              <summary>이 턴 뒤의 유효 사실 {Object.keys(t.effective_facts || {}).length}개</summary>
              <Json value={Object.fromEntries(Object.entries(t.effective_facts || {}).map(([k, f]) => [k, `${JSON.stringify(f.value)} (${f.status}, ${f.source_type})`]))} />
            </details>
          </section>
        );
      })}
    </div>
  );
}
