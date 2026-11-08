// 개발용 회사 선택. 로그인은 다른 팀 담당이라, 참조 구현은 X-Company-Id를 localStorage에 둔다.
const CURRENT = 'wd.companyId';
const KNOWN = 'wd.knownCompanies';

function read(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}
function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 저장소를 쓸 수 없으면 이번 창에서만 유지 */
  }
}

/** @returns {string|null} */
export function getCompanyId() {
  return read(CURRENT, null);
}

/** @param {string|null} id */
export function setCompanyId(id) {
  if (id) write(CURRENT, id);
  else {
    try {
      localStorage.removeItem(CURRENT);
    } catch {
      /* noop */
    }
  }
  window.dispatchEvent(new Event('wd-company-change'));
}

/** @returns {{id: string, name: string}[]} 이 브라우저에서 만들거나 고른 회사 */
export function knownCompanies() {
  const list = read(KNOWN, []);
  return Array.isArray(list) ? list : [];
}

/** @param {{id: string, name: string}} c */
export function rememberCompany(c) {
  const list = knownCompanies().filter((x) => x.id !== c.id);
  write(KNOWN, [{ id: c.id, name: c.name }, ...list].slice(0, 20));
}

/** @param {string} id */
export function forgetCompany(id) {
  write(KNOWN, knownCompanies().filter((x) => x.id !== id));
}
