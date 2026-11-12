import { useMemo, useState } from 'react';
import { api } from '../api/index.js';
import { useLoad } from '../lib/useLoad.js';

/** 오른쪽 상세 패널에 보일 내용 */
function Detail({ sel }) {
  if (!sel) return <p className="muted">카드나 표의 칸을 누르면 여기에 규칙·소재 목록이 보여요.</p>;
  return (
    <>
      <h3>{sel.title}</h3>
      {sel.sub && <p className="muted small">{sel.sub}</p>}
      {sel.sections.map((s) => (
        <div key={s.h}>
          <h4>{s.h}</h4>
          <ul className="rg-list">{s.items.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </div>
      ))}
    </>
  );
}

function Overview({ ov, onSelect }) {
  const special = ov.laws.filter((l) => !l.common);
  const common = ov.laws.filter((l) => l.common);
  return (
    <div className="rg">
      <div className="rg-step rg-start">문진 시작: 소재·상태·답변</div>
      {ov.stages.map((s) => (
        <div key={s.id}>
          <div className="rg-arrow">↓</div>
          <div className="rg-stage-row">
            <button type="button" className="rg-step" onClick={() => onSelect({ title: s.label, sections: [{ h: `규칙 ${s.rules.length}개`, items: s.rules }] })}>
              <strong>{s.label}</strong>
              <span className="muted small">규칙 {s.rules.length}개</span>
            </button>
            <span className="rg-exit">해당하면 →</span>
            <span className="rg-stop">{s.stop}</span>
          </div>
        </div>
      ))}
      <div className="rg-arrow">↓ 사업장폐기물이면 소재별로</div>

      <div className="rg-section">
        <h3>소재 분류 × 지정폐기물 기준(시행령 별표 1)</h3>
        <p className="muted small">숫자는 그 기준을 확인하는 소재 수예요. 칸을 누르면 소재 목록, 열 머리를 누르면 규칙 목록이 보여요.</p>
        <div className="rg-table-wrap">
          <table className="rg-table">
            <thead>
              <tr>
                <th>소재 분류</th>
                {special.map((l) => (
                  <th key={l.id}>
                    <button type="button" onClick={() => onSelect({ title: l.label, sub: `소재 ${l.materials}개에 적용`, sections: [{ h: `규칙 ${l.rules.length}개`, items: l.rules }] })}>{l.label}</button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ov.groups.map((g) => (
                <tr key={g.id}>
                  <th>
                    <button type="button" onClick={() => onSelect({ title: g.label, sections: [{ h: `소재 ${g.materials.length}개`, items: g.materials }] })}>
                      {g.label} <span className="muted small">({g.materials.length})</span>
                    </button>
                  </th>
                  {special.map((l) => {
                    const mats = ov.matrix[g.id]?.[l.id] || [];
                    return (
                      <td key={l.id}>
                        {mats.length > 0 && (
                          <button type="button" className="rg-cell" onClick={() => onSelect({ title: `${g.label} × ${l.label}`, sections: [{ h: `소재 ${mats.length}개`, items: mats }, { h: '규칙', items: l.rules }] })}>{mats.length}</button>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rg-common">
          <span className="muted small">모든 소재 공통(오염 확인):</span>
          {common.map((l) => (
            <button key={l.id} type="button" className="rg-chip" onClick={() => onSelect({ title: l.label, sub: `소재 ${l.materials}개에 적용`, sections: [{ h: `규칙 ${l.rules.length}개`, items: l.rules }] })}>
              {l.label} · 규칙 {l.rules.length}
            </button>
          ))}
        </div>
      </div>

      <div className="rg-arrow">↓</div>
      <div className="rg-outcomes">
        <div className="rg-out">기준에 하나라도 맞으면<br /><strong>지정폐기물 분류번호</strong></div>
        <div className="rg-out">잔류물 등 법 조문만으로 못 정하면<br /><strong>해석 필요(관할 기관 확인)</strong></div>
        <div className="rg-out">지정 기준에 해당 없으면<br /><strong>일반 분류번호</strong></div>
      </div>
    </div>
  );
}

function TableFlow({ tg, q, onSelect }) {
  const match = (r) => !q || [r.source_rule, r.plain, ...r.conditions, ...r.outcomes].join(' ').toLowerCase().includes(q.toLowerCase());
  return (
    <div className="rg">
      {tg.bands.map((b, i) => {
        const rules = b.rules.filter(match);
        if (rules.length === 0) return null;
        return (
          <div key={b.priority} className="rg-band">
            {i > 0 && <div className="rg-arrow">↓ 위 단계에 해당 없으면</div>}
            <h4>{b.label} <span className="muted small">규칙 {rules.length}개</span></h4>
            <div className="rg-cards">
              {rules.map((r) => (
                <button key={r.id} type="button" className="rg-card" onClick={() => onSelect({ title: r.source_rule, sub: r.plain, sections: [{ h: '조건(모두 맞아야 함)', items: r.conditions.length ? r.conditions : ['(추가 조건 없음)'] }, { h: '결론', items: r.outcomes }] })}>
                  <ul className="rg-cond">{(r.conditions.length ? r.conditions : ['(추가 조건 없음)']).slice(0, 4).map((c, k) => <li key={k}>{c}</li>)}{r.conditions.length > 4 && <li className="muted">…외 {r.conditions.length - 4}개</li>}</ul>
                  <div className="rg-then">→ {r.outcomes[0]}{r.outcomes.length > 1 ? ` 외 ${r.outcomes.length - 1}개` : ''}</div>
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** 개발자용: 엔진 규칙 전체 구조와 소재별 판정 흐름(API /dev/rules, prod 404) */
export default function RulesGraphPage() {
  const { data: ov, error } = useLoad(() => api.devOverview(), []);
  const { data: tables } = useLoad(() => api.devTables().catch(() => []), []);
  const [sel, setSel] = useState(null);
  const [tab, setTab] = useState('overview');
  const [tableId, setTableId] = useState('pp');
  const [q, setQ] = useState('');
  const { data: tg } = useLoad(() => (tab === 'table' && tableId ? api.devTableGraph(tableId) : Promise.resolve(null)), [tab, tableId]);
  const sorted = useMemo(() => tables || [], [tables]);

  if (error) return <p className="wd-alert" role="alert">규칙 그래프를 불러오지 못했어요(개발 환경에서만 열립니다): {error.message}</p>;
  if (!ov) return <p className="muted">불러오는 중…</p>;

  return (
    <div className="dev-page">
      <h2>엔진 규칙</h2>
      <p className="muted small">
        소재 {ov.stats.materials}개 · 원본 법 규칙 {ov.stats.law_rules}개 · 소재별 규칙 표 {ov.stats.tables}개 · 엔진 규칙 {ov.stats.engine_rules}개. 위에서 아래로 판정 순서예요.
      </p>
      <div className="row rg-tabs">
        <button type="button" className={`button button-small ${tab === 'overview' ? 'button-primary' : 'button-quiet'}`} onClick={() => { setTab('overview'); setSel(null); }}>전체 구조</button>
        <button type="button" className={`button button-small ${tab === 'table' ? 'button-primary' : 'button-quiet'}`} onClick={() => { setTab('table'); setSel(null); }}>소재별 판정 흐름</button>
        {tab === 'table' && (
          <>
            <select value={tableId} onChange={(e) => { setTableId(e.target.value); setSel(null); }} aria-label="소재">
              {sorted.map((t) => <option key={t.table_id} value={t.table_id}>{t.title} ({t.rules})</option>)}
            </select>
            <input className="wd-input" placeholder="규칙·조건 검색 (예: 기름, PCB)" value={q} onChange={(e) => setQ(e.target.value)} />
          </>
        )}
      </div>
      <div className="rg-layout">
        <div>{tab === 'overview' ? <Overview ov={ov} onSelect={setSel} /> : tg ? <TableFlow tg={tg} q={q} onSelect={setSel} /> : <p className="muted">불러오는 중…</p>}</div>
        <aside className="wd-card rg-detail"><Detail sel={sel} /></aside>
      </div>
    </div>
  );
}
