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

/** 개발자용: 턴마다 AI에 보낸 데이터·받은 값·검사 결과·엔진 판단(Trace 기반) */
export default function DevTracePage({ id }) {
  const { data: trace, error } = useLoad(() => api.trace(id), [id]);
  if (error) return <p className="wd-alert" role="alert">{error.message}</p>;
  if (!trace) return <p className="muted">불러오는 중…</p>;
  const turns = trace.sessions.flatMap((s) => s.turns.filter((t) => t.kind === 'TURN'));

  return (
    <div className="dev-page">
      <div className="row between">
        <h2>AI 데이터 확인 (개발자용)</h2>
        <a className="button button-small button-quiet" href={`#/cases/${id}`}>← 문진으로</a>
      </div>
      <p className="muted">턴마다 AI에 보낸 데이터와 받은 값, guard 검사, 엔진이 고른 분기와 질문 점수를 보여 줍니다. 판정은 엔진 규칙만 정합니다.</p>
      {turns.length === 0 && <p className="muted">아직 기록된 턴이 없어요.</p>}
      {turns.map((row, i) => {
        const t = row.payload;
        const ex = t.extraction;
        return (
          <section key={row.seq} className="wd-card dev-turn">
            <h3>턴 {i + 1} · {t.branch} <span className="muted small">{row.turn_id}</span></h3>
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
            <details>
              <summary>응답 검사·보충 설명</summary>
              <Json value={t.responder} />
              {t.response?.assist && <Json value={t.response.assist} />}
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
