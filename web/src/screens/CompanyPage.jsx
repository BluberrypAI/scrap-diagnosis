import { useEffect, useState } from 'react';
import { api } from '../api/index.js';
import { forgetCompany, getCompanyId, knownCompanies, rememberCompany, setCompanyId } from '../api/company.js';
import { useLoad } from '../lib/useLoad.js';

/** 개발용 회사 선택(X-Company-Id) */
function Picker({ onChange }) {
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const [list, setList] = useState(knownCompanies());
  const cur = getCompanyId();
  const pick = (c) => {
    setCompanyId(c.id);
    rememberCompany(c);
    setList(knownCompanies());
    onChange();
  };
  async function create() {
    setErr('');
    try {
      const c = await api.createCompany(name.trim());
      pick({ id: c.id, name: c.name });
      setName('');
    } catch (e) {
      setErr(e.message);
    }
  }
  return (
    <section className="wd-card">
      <h3>개발용 회사 선택</h3>
      <p className="muted">로그인은 다른 팀이 맡아서, 여기서는 회사를 만들거나 골라 X-Company-Id를 정합니다.</p>
      <ul className="plain">
        {list.map((c) => (
          <li key={c.id} className="row">
            <button type="button" className={`button button-small ${c.id === cur ? 'button-primary' : 'button-quiet'}`} onClick={() => pick(c)}>{c.name}{c.id === cur ? ' (사용 중)' : ''}</button>
            <button type="button" className="button button-small button-link" onClick={() => { forgetCompany(c.id); setList(knownCompanies()); }}>목록에서 지우기</button>
          </li>
        ))}
      </ul>
      <div className="row">
        <input className="wd-input" aria-label="새 회사 이름" placeholder="새 회사 이름" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="button" className="button button-primary" disabled={!name.trim()} onClick={create}>회사 만들기</button>
      </div>
      {err && <p className="wd-alert" role="alert">{err}</p>}
    </section>
  );
}

function ProfileForm({ company }) {
  const { data: opts } = useLoad(() => api.profileOptions(), []);
  const p = company.profile || {};
  const [basic, setBasic] = useState({ company_name: company.name, industry: '', address: '', ...(p.basic || {}) });
  const [fac, setFac] = useState(p.facilities || []);
  const [products, setProducts] = useState(p.products || []);
  const [tag, setTag] = useState('');
  const [saved, setSaved] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => setSaved(p.facts || null), []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (v) => setFac((f) => (v === 'none' ? (f.includes('none') ? [] : ['none']) : f.includes(v) ? f.filter((x) => x !== v) : [...f.filter((x) => x !== 'none'), v]));
  const addTag = () => {
    if (tag.trim()) setProducts((x) => [...x, tag.trim()]);
    setTag('');
  };
  async function save() {
    setErr('');
    try {
      const c = await api.updateProfile({ basic, facilities: fac, products });
      setSaved((c.profile || c).facts || {});
    } catch (e) {
      setErr(e.message);
    }
  }
  const set = (k) => (e) => setBasic((b) => ({ ...b, [k]: e.target.value }));
  return (
    <section className="wd-card">
      <h3>기업 정보 · {company.name}</h3>
      <label className="wd-field"><span>회사명</span><input className="wd-input" value={basic.company_name} onChange={set('company_name')} /></label>
      <label className="wd-field"><span>업종</span><input className="wd-input" value={basic.industry} onChange={set('industry')} /></label>
      <label className="wd-field"><span>주소</span><input className="wd-input" value={basic.address} onChange={set('address')} /></label>
      <h4>배출시설</h4>
      <div className="row wrap">
        {(opts?.facilities || []).map((o) => (
          <button key={o.value} type="button" aria-pressed={fac.includes(o.value)} className={`wd-chip chip-toggle${fac.includes(o.value) ? ' is-on' : ''}`} onClick={() => toggle(o.value)}>{o.label}</button>
        ))}
      </div>
      <h4>주생산품</h4>
      <div className="row wrap">
        {products.map((x, i) => <button key={i} type="button" className="wd-chip" title="누르면 지워요" onClick={() => setProducts((l) => l.filter((_, j) => j !== i))}>{x} ✕</button>)}
        <input className="wd-input" aria-label="생산품 추가" placeholder="생산품 입력 후 Enter" value={tag} onChange={(e) => setTag(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); addTag(); } }} />
      </div>
      {err && <p className="wd-alert" role="alert">{err}</p>}
      <button type="button" className="button button-primary" onClick={save}>저장</button>
      {saved && Object.keys(saved).length > 0 && (
        <p className="wd-alert is-info">배출시설 정보는 문진에서 다시 묻지 않습니다. 반영된 사실: {Object.entries(saved).map(([k, v]) => `${k}=${v}`).join(', ')}</p>
      )}
    </section>
  );
}

export default function CompanyPage() {
  const [n, setN] = useState(0);
  const has = !!getCompanyId();
  const { data: company, error } = useLoad(() => (has ? api.getMyCompany() : Promise.resolve(null)), [n, has]);
  return (
    <div className="stack">
      <h2>기업 정보</h2>
      <Picker onChange={() => setN((x) => x + 1)} />
      {has && error && <p className="wd-alert" role="alert">{error.message}</p>}
      {has && company && <ProfileForm key={company.id} company={company} />}
      {has && company && <a className="button button-quiet" href="#/cases">내 폐기물로</a>}
    </div>
  );
}
