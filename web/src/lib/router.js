// 작은 해시 라우터. scrap-web src/lib/router.js와 같은 currentRoute/navigate를 쓰되,
// scrap-web처럼 hashchange마다 새로고침하지 않고 React 상태로 다시 그린다.
import { useEffect, useState } from 'react';

/** @typedef {{path: string, search: string, params: Record<string,string>, name: string}} Route */

/** 현재 해시에서 경로와 쿼리를 읽는다. 예: #/cases/abc?x=1 → {path:'/cases/abc', search:'?x=1'} */
export function currentRoute() {
  let hash = window.location.hash.slice(1) || '/';
  hash = hash.split('#')[0];
  const q = hash.indexOf('?');
  const path = (q < 0 ? hash : hash.slice(0, q)).replace(/\/+$/, '') || '/';
  return { path, search: q < 0 ? '' : hash.slice(q) };
}

/** @param {string} url 예: '/cases/abc' */
export function navigate(url) {
  window.location.hash = '#' + url;
}

const ROUTES = [
  { name: 'company', re: /^\/company$/ },
  { name: 'dev-company', re: /^\/dev\/company$/ },
  { name: 'new-case', re: /^\/cases\/new$/ },
  { name: 'history', re: /^\/cases\/([^/]+)\/history$/, keys: ['id'] },
  { name: 'dev-trace', re: /^\/cases\/([^/]+)\/dev$/, keys: ['id'] },
  { name: 'dev-rules', re: /^\/dev\/rules$/ },
  { name: 'case', re: /^\/cases\/([^/]+)$/, keys: ['id'] },
  { name: 'cases', re: /^\/(cases)?$/ },
];

/** @param {string} path @returns {Route} */
export function matchRoute(path, search = '') {
  for (const r of ROUTES) {
    const m = path.match(r.re);
    if (m) {
      /** @type {Record<string,string>} */
      const params = {};
      (r.keys || []).forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])));
      return { name: r.name, path, search, params };
    }
  }
  return { name: 'not-found', path, search, params: {} };
}

/** @returns {Route} */
export function useRoute() {
  const [route, setRoute] = useState(() => {
    const { path, search } = currentRoute();
    return matchRoute(path, search);
  });
  useEffect(() => {
    const on = () => {
      const { path, search } = currentRoute();
      setRoute(matchRoute(path, search));
      if (!/jsdom/.test(navigator.userAgent)) window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}
