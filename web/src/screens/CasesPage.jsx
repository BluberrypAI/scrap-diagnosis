import { useState } from 'react';
import { api } from '../api/index.js';
import { formatRelative } from '../lib/format.js';
import { useLoad } from '../lib/useLoad.js';

const TABS = [
  ['ALL', '전체', () => true],
  ['DIAGNOSING', '문진 중', (c) => c.status === 'DIAGNOSING'],
  ['NEEDS_INFO', '추가 정보 필요', (c) => c.status === 'NEEDS_INFO'],
  ['CODE_CONFIRMED', '확정', (c) => c.status === 'CODE_CONFIRMED'],
  ['HISTORY', '이력', (c) => c.status === 'IN_TRANSIT' || c.status === 'COMPLETED'],
];

export default function CasesPage() {
  const { data: cases, error, loading } = useLoad(() => api.listCases(), []);
  const { data: company } = useLoad(() => api.getMyCompany().catch(() => null), []);
  const [tab, setTab] = useState('ALL');
  const filter = TABS.find((t) => t[0] === tab)[2];
  const list = (cases || []).filter(filter);
  const noProfile = company && !(company.profile && company.profile.basic);

  return (
    <div>
      <div className="row between">
        <h2>내 폐기물</h2>
        <a className="button button-primary" href="#/cases/new">새 문진</a>
      </div>
      {noProfile && <p className="wd-alert is-info">기업 정보를 먼저 입력하면 질문이 줄어듭니다. <a href="#/company">기업 정보 입력</a></p>}
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`button button-small ${tab === k ? 'button-primary' : 'button-quiet'}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {error && <p className="wd-alert" role="alert">{error.message}</p>}
      {loading && <p className="muted">불러오는 중…</p>}
      {!loading && !error && list.length === 0 && (
        <p className="wd-card">아직 문진한 폐기물이 없어요 <a className="button button-small button-primary" href="#/cases/new">새 문진</a></p>
      )}
      <div className="card-list">
        {list.map((c) => (
          <a key={c.id} className="wd-card case-card" href={`#/cases/${c.id}`}>
            <div className="row between">
              <strong>{c.summary.title}</strong>
              <span className={`status-badge${c.status === 'CODE_CONFIRMED' ? ' is-complete' : ''}`} data-status={c.status}>{c.summary.status_label}</span>
            </div>
            <div>{c.summary.result_label || '미정'}</div>
            <div className="muted">{c.summary.next_action} · {formatRelative(c.updated_at)}</div>
          </a>
        ))}
      </div>
    </div>
  );
}
