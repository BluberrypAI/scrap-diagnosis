import { useEffect, useState } from 'react';
import { api, USE_MOCK } from './api/index.js';
import { getCompanyId } from './api/company.js';
import { navigate, useRoute } from './lib/router.js';
import CompanyPage from './screens/CompanyPage.jsx';
import CasesPage from './screens/CasesPage.jsx';
import NewCasePage from './screens/NewCasePage.jsx';
import CasePage from './screens/CasePage.jsx';
import HistoryPage from './screens/HistoryPage.jsx';

export default function App() {
  const route = useRoute();
  const [cid, setCid] = useState(getCompanyId());
  useEffect(() => {
    const on = () => setCid(getCompanyId());
    window.addEventListener('wd-company-change', on);
    return () => window.removeEventListener('wd-company-change', on);
  }, []);
  const isCompany = route.name === 'company' || route.name === 'dev-company';
  useEffect(() => {
    if (!cid && !isCompany) navigate('/company');
  }, [cid, isCompany]);
  useEffect(() => {
    if (cid) api.catalogFacts().catch(() => {});
  }, [cid]);

  let page;
  if (isCompany) page = <CompanyPage />;
  else if (!cid) page = null;
  else if (route.name === 'cases') page = <CasesPage />;
  else if (route.name === 'new-case') page = <NewCasePage />;
  else if (route.name === 'case') page = <CasePage key={route.params.id} id={route.params.id} />;
  else if (route.name === 'history') page = <HistoryPage key={route.params.id} id={route.params.id} />;
  else page = <p>없는 화면이에요. <a href="#/cases">목록으로</a></p>;

  return (
    <div className="l3-shell">
      <header className="l3-workbar">
        <strong>폐기물 문진</strong>
        <div>
          <a href="#/cases">내 폐기물</a>
          <a href="#/company">기업 정보</a>
          {USE_MOCK && <span className="wd-chip">목 API</span>}
        </div>
      </header>
      <main className="page">{page}</main>
    </div>
  );
}
