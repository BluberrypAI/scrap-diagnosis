// 모든 API 호출. 오류 처리는 docs/ui/ui-design.md §5를 따른다.
//  - 오류 문구는 detail.message (문자열 detail도 받는다)
//  - 401 → onUnauthorized (개발용 회사 선택으로)
//  - 409 → kind 'stale'(동시 수정: 새로 불러오기) / 'conflict'(확정 불가 등: 서버 문구 그대로)
//  - 422 검증 오류(FastAPI 기본 형식) → "입력값을 확인해 주세요"
//  - 네트워크 오류 → kind 'network' (화면은 입력을 지우지 않고 다시 보내기를 보여 준다)
import { getCompanyId } from './company.js';
import { normalizeCase, normalizeDetail, normalizeTurn, setCatalog } from './normalize.js';
import { FALLBACK_FACILITIES } from '../lib/labels.js';

export const NETWORK_MESSAGE = '서버에 연결하지 못했어요. 연결을 확인하고 다시 보내 주세요.';
export const STALE_MESSAGE = '다른 창에서 이 건이 바뀌었어요. 새로 불러옵니다';
export const VALIDATION_MESSAGE = '입력값을 확인해 주세요';

export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {{status?: number, kind?: 'network'|'unauthorized'|'stale'|'conflict'|'validation'|'not_found'|'http', detail?: any}} [o]
   */
  constructor(message, { status = 0, kind = 'http', detail = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
    this.detail = detail;
  }
}

/** @param {number} status @param {any} body */
export function toApiError(status, body) {
  const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body;
  let message =
    (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) ||
    (typeof detail === 'string' ? detail : null);
  /** @type {ApiError['kind']} */
  let kind = 'http';
  if (status === 401) kind = 'unauthorized';
  else if (status === 404) kind = 'not_found';
  else if (status === 422) {
    kind = 'validation';
    if (Array.isArray(detail) || !message) message = VALIDATION_MESSAGE;
  } else if (status === 409) {
    const code = detail && typeof detail === 'object' ? detail.code : null;
    kind = code === 'STALE' || /먼저 갱신|동시/.test(message || '') ? 'stale' : 'conflict';
  }
  return new ApiError(message || `요청을 처리하지 못했어요(${status})`, { status, kind, detail });
}

/**
 * @param {{base?: string, transport?: (url: string, init: RequestInit) => Promise<{status: number, text: () => Promise<string>}>,
 *   companyId?: () => string|null, onUnauthorized?: (e: ApiError) => void}} [opts]
 */
export function createClient(opts = {}) {
  const base = (opts.base ?? (import.meta.env.VITE_API_BASE || '/api')).replace(/\/$/, '');
  const transport = opts.transport || ((url, init) => fetch(url, init));
  const companyId = opts.companyId || getCompanyId;
  const onUnauthorized = opts.onUnauthorized || (() => {});

  /** @param {string} method @param {string} path @param {any} [body] @param {{auth?: boolean}} [o] */
  async function request(method, path, body, { auth = true } = {}) {
    /** @type {Record<string,string>} */
    const headers = { Accept: 'application/json' };
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
    if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
    const cid = companyId();
    if (auth && cid) headers['X-Company-Id'] = cid;
    let res;
    try {
      res = await transport(base + path, {
        method,
        headers,
        body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      });
    } catch (e) {
      if (e && e.name === 'AbortError') throw e;
      throw new ApiError(NETWORK_MESSAGE, { kind: 'network' });
    }
    let data = null;
    try {
      const text = await res.text();
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    if (res.status >= 400) {
      const err = toApiError(res.status, data);
      if (err.kind === 'unauthorized') onUnauthorized(err);
      throw err;
    }
    return data;
  }

  /** 새 엔드포인트가 아직 없을 때(404/405) 대체값 */
  async function optional(path, fallback) {
    try {
      return await request('GET', path);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return fallback;
      throw e;
    }
  }

  return {
    request,
    // ---- 기업 ----
    /** @param {string} name @param {object} [profile] */
    createCompany: (name, profile = {}) => request('POST', '/companies', { name, profile }, { auth: false }),
    getMyCompany: () => request('GET', '/companies/me'),
    /** @param {object} profile */
    updateProfile: (profile) => request('PUT', '/companies/me/profile', { profile }),
    profileOptions: () => optional('/companies/profile-options', { facilities: FALLBACK_FACILITIES, _fallback: true }),
    catalogFacts: async () => {
      const list = await optional('/catalog/facts', []);
      setCatalog(list);
      return list;
    },
    // ---- 건 ----
    /** @param {string} [status] */
    listCases: async (status) => (await request('GET', '/cases' + (status ? `?status=${encodeURIComponent(status)}` : ''))).map(normalizeCase),
    /** @param {{memo?: string|null, quantity?: number|null, unit?: string|null, period?: string|null}} body */
    createCase: async (body) => {
      const d = await request('POST', '/cases', body);
      return { case: normalizeCase(d.case), turn: normalizeTurn(d.turn) };
    },
    /** @param {string} id */
    getCase: async (id) => normalizeDetail(await request('GET', `/cases/${encodeURIComponent(id)}`)),
    // ---- 문진 ----
    /** @param {string} id @param {{text?: string, quick_reply?: {key: string, kind: string, value?: any}}} msg */
    sendMessage: async (id, msg) => normalizeTurn(await request('POST', `/cases/${encodeURIComponent(id)}/diagnosis/messages`, msg)),
    /** @param {string} id @param {File|Blob} file @param {Record<string, any>|null} [facts] */
    uploadDocument: async (id, file, facts = null) => {
      const form = new FormData();
      form.append('file', file, /** @type {any} */ (file).name || 'document');
      if (facts && Object.keys(facts).length) form.append('facts', JSON.stringify(facts));
      const d = await request('POST', `/cases/${encodeURIComponent(id)}/documents`, form);
      return { document: d.document, turn: normalizeTurn(d.turn) };
    },
    /** @param {string} id @param {string|null} [expected_code] */
    confirm: async (id, expected_code = null) => {
      const d = await request('POST', `/cases/${encodeURIComponent(id)}/confirm`, expected_code ? { expected_code } : {});
      return { ...d, case: normalizeCase(d.case) };
    },
    /** @param {string} id @param {string|null} reason */
    reopen: async (id, reason) => {
      const d = await request('POST', `/cases/${encodeURIComponent(id)}/reopen`, { reason: reason || null });
      return { ...d, case: normalizeCase(d.case), turn: normalizeTurn(d.turn) };
    },
    /** @param {string} id */
    trace: (id) => request('GET', `/cases/${encodeURIComponent(id)}/trace`),
  };
}

/** @typedef {ReturnType<typeof createClient>} Client */
