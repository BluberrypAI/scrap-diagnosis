import { useCallback, useState } from 'react';
import { api } from '../api/index.js';
import { useLoad } from '../lib/useLoad.js';
import Mermaid from '../components/Mermaid.jsx';

/** 개발자용: 엔진 규칙 전체 구조 한 장 + 소재별 규칙 흐름(API /dev/rules, prod 404) */
export default function RulesGraphPage() {
  const { data: ov, error } = useLoad(() => api.devOverview(), []);
  const { data: tables } = useLoad(() => api.devTables().catch(() => []), []);
  const [picked, setPicked] = useState(null);
  const [tableId, setTableId] = useState('');
  const { data: tg } = useLoad(() => (tableId ? api.devTableGraph(tableId) : Promise.resolve(null)), [tableId]);
  const onNode = useCallback((id) => setPicked(id), []);

  if (error) return <p className="wd-alert" role="alert">규칙 그래프를 불러오지 못했어요(개발 환경에서만 열립니다): {error.message}</p>;
  if (!ov) return <p className="muted">불러오는 중…</p>;
  const node = picked && ov.nodes[picked];
  const tableRule = picked && tg && tg.bands.flatMap((b) => b.rules).find((r) => r.source_rule === picked);

  return (
    <div className="dev-page">
      <h2>엔진 규칙 전체 구조</h2>
      <p className="muted">
        소재 {ov.stats.materials}개 · 원본 법 규칙 {ov.stats.law_rules}개 · 소재별 규칙 표 {ov.stats.tables}개 · 엔진 규칙 {ov.stats.engine_rules}개.
        위에서 아래로 판정 순서입니다. 상자를 누르면 규칙 목록이 보여요.
      </p>
      <div className="dev-graph-row">
        <div className="dev-graph"><Mermaid code={ov.mermaid} onNodeClick={onNode} /></div>
        <aside className="wd-card dev-detail">
          {node ? (
            <>
              <h3>{node.title}</h3>
              <ul className="plain small">{node.detail.map((d, i) => <li key={i}>{d}</li>)}</ul>
            </>
          ) : tableRule ? (
            <>
              <h3>{tableRule.source_rule}</h3>
              {tableRule.plain && <p>{tableRule.plain}</p>}
              <h4>조건(모두 맞아야 함)</h4>
              <ul className="plain small">{tableRule.conditions.map((c, i) => <li key={i}>{c}</li>)}</ul>
              <h4>결론</h4>
              <ul className="plain small">{tableRule.outcomes.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </>
          ) : (
            <p className="muted">그래프의 상자를 누르세요.</p>
          )}
        </aside>
      </div>

      <h2>소재별 규칙 흐름</h2>
      <label className="row">
        <span>소재</span>
        <select value={tableId} onChange={(e) => { setTableId(e.target.value); setPicked(null); }}>
          <option value="">고르세요</option>
          {(tables || []).map((t) => <option key={t.table_id} value={t.table_id}>{t.title} ({t.rules}개)</option>)}
        </select>
      </label>
      {tg && <div className="dev-graph"><Mermaid code={tg.mermaid} onNodeClick={onNode} /></div>}
    </div>
  );
}
