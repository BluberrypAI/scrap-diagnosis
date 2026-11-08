// 백엔드 없이 문진 흐름을 돌리는 목 API. fixtures/scenario-*.json의 단계(step)를 따라간다.
// 상태는 메모리에만 있다(새로고침하면 사라짐). 클라이언트(client.js)와 같은 메서드를 가진다.
import pp from './fixtures/scenario-pp.json';
import sludge from './fixtures/scenario-sludge.json';
import acid from './fixtures/scenario-acid.json';
import profileOptions from './fixtures/profile-options.json';
import catalog from './fixtures/catalog-facts.json';
import { ApiError } from '../client.js';
import { getCompanyId } from '../company.js';
import { normalizeCase, normalizeDetail, normalizeTurn, setCatalog } from '../normalize.js';
import { OUTCOME_LABEL, STATUS_LABEL, NEXT_ACTION } from '../../lib/labels.js';

const SCENARIOS = [sludge, acid, pp];
const clone = (o) => JSON.parse(JSON.stringify(o));
const nowIso = () => new Date().toISOString();
let seq = 0;
const uid = (p) => `${p}-${++seq}-${Math.random().toString(36).slice(2, 6)}`;
const wait = () => new Promise((r) => setTimeout(r, Number(import.meta.env.VITE_MOCK_DELAY ?? 450)));

export function createMockClient() {
  const companies = {};
  const cases = [];

  const me = () => {
    const id = getCompanyId();
    if (!id) throw new ApiError('X-Company-Id 헤더가 필요합니다', { status: 401, kind: 'unauthorized' });
    return (companies[id] ||= { id, name: '개발용 회사', profile: {} });
  };
  const find = (id) => {
    const rec = cases.find((c) => c.c.id === id && c.c.company_id === me().id);
    if (!rec) throw new ApiError('건을 찾을 수 없습니다', { status: 404, kind: 'not_found' });
    return rec;
  };
  const step = (rec) => rec.sc.steps[rec.step];
  const question = (rec) => step(rec).turn.ui.question;

  function applyEdits(board, edits) {
    board.facts = board.facts.flatMap((f) => {
      const e = edits[f.key];
      if (!e) return [f];
      if (e.retract) {
        board.pending.push({ key: f.key, label: f.label, reason: 'MISSING' });
        return [];
      }
      const o = f.edit?.options?.find((x) => x.value === e.value);
      return [{ ...f, value: e.value, value_label: o?.label ?? String(e.value) }];
    });
  }

  /** 현재 단계의 턴을 만들고 건 상태·요약을 맞춘다 */
  function makeTurn(rec) {
    const t = clone(step(rec).turn);
    Object.assign(t, { case_id: rec.c.id, session_id: rec.session, turn_id: uid('turn') });
    applyEdits(t.ui.board, rec.edits);
    if (rec.c.status !== 'CODE_CONFIRMED') rec.c.status = t.case_status || 'DIAGNOSING';
    const res = t.ui.result;
    if (res) rec.c.summary.result_label = res.code ? `${res.code} ${res.name}` : OUTCOME_LABEL[res.outcome] || res.conclusion;
    const mat = t.ui.board.facts.find((f) => f.key === 'material');
    if (mat && !rec.c.memo) rec.c.summary.title = mat.value_label;
    rec.c.updated_at = nowIso();
    rec.c.summary.status_label = STATUS_LABEL[rec.c.status];
    rec.c.summary.next_action = NEXT_ACTION[rec.c.status];
    return t;
  }

  function labelOf(rec, qr) {
    const o = (question(rec)?.options || []).find((x) => x.kind === qr.kind && (qr.kind !== 'value' || x.value === qr.value));
    if (o) return o.label;
    return qr.kind === 'retract' ? '모름으로 되돌리기' : qr.kind === 'unknown' ? '모름' : `${qr.key} = ${JSON.stringify(qr.value)}`;
  }

  /** 입력에 따라 다음 단계로 간다. 보드 사실을 고치는 입력(edit)은 같은 단계에 머문다 */
  function advance(rec, input) {
    const s = step(rec);
    const q = s.turn.ui.question;
    const qr = input.quick_reply;
    let key = 'default';
    let edit = false;
    if (input.upload) key = 'upload';
    else if (input.text && input.text.includes('서류가 없')) key = 'refuse';
    else if (qr) {
      if (qr.kind === 'retract') edit = true;
      else if (qr.kind === 'none_all' || qr.kind === 'expand') key = qr.kind;
      else if (qr.kind === 'value') {
        if (s.turn.branch === 'FINAL_REVIEW' || (q && qr.key !== q.key)) edit = true;
        else key = `value:${String(qr.value).toLowerCase()}`;
      }
    }
    if (edit) {
      rec.edits[qr.key] = qr.kind === 'retract' ? { retract: true } : { value: qr.value };
      return;
    }
    const next = s.next?.[key] ?? s.next?.default;
    if (next && rec.sc.steps[next]) rec.step = next;
  }

  function record(rec, userText, input, turn) {
    const at = nowIso();
    rec.conv.push({ turn_id: turn.turn_id, role: 'user', text: userText, quick_reply: input.quick_reply || null, at });
    rec.conv.push({ turn_id: turn.turn_id, role: 'assistant', text: turn.message, branch: turn.branch, question_key: turn.ui.question?.key || null, at });
    rec.trace.push({
      seq: rec.trace.length + 1, kind: 'TURN', turn_id: turn.turn_id, immutable: false, recorded_at: at,
      payload: { user_input: userText, branch: turn.branch, branch_reason: step(rec).branch_reason },
    });
  }

  function locked(rec) {
    if (rec.c.status === 'CODE_CONFIRMED')
      throw new ApiError('확정된 건은 다시 열기 전에는 고칠 수 없습니다', { status: 409, kind: 'conflict' });
  }

  function newCase(body) {
    const memo = (body.memo || '').trim() || null;
    const sc = SCENARIOS.find((s) => memo && s.match.some((m) => memo.toLowerCase().includes(m.toLowerCase()))) || pp;
    const at = nowIso();
    const rec = {
      sc, step: memo ? sc.start.memo : sc.start.empty, edits: {}, conv: [], docs: [], verdicts: [], handoff: null, trace: [],
      session: uid('sess'),
      c: {
        id: uid('case'), company_id: me().id, memo, quantity: body.quantity ?? null, unit: body.unit ?? null, period: body.period ?? null,
        status: 'DIAGNOSING', created_at: at, updated_at: at, as_of: at.slice(0, 10),
        summary: { title: memo ? memo.split('\n')[0].slice(0, 30) : '새 폐기물', code: null, outcome: null, result_label: null },
      },
    };
    cases.unshift(rec);
    return rec;
  }

  return {
    async createCompany(name, profile = {}) {
      await wait();
      const c = { id: uid('co'), name, profile };
      companies[c.id] = c;
      return c;
    },
    async getMyCompany() {
      await wait();
      return me();
    },
    async updateProfile(profile) {
      await wait();
      const c = me();
      const fac = profile.facilities || [];
      const facts = { ...(profile.facts || {}) };
      if (fac.some((f) => ['air_emission', 'water_emission', 'noise_vibration'].includes(f))) facts.emission_facility = true;
      else if (fac.includes('none')) facts.emission_facility = false;
      if (fac.includes('waste_treatment')) facts.waste_facility = true;
      c.profile = { ...profile, facts };
      return c;
    },
    async profileOptions() {
      return profileOptions;
    },
    async catalogFacts() {
      setCatalog(catalog);
      return catalog;
    },
    async listCases(status) {
      await wait();
      const cid = me().id;
      return cases.filter((r) => r.c.company_id === cid && (!status || r.c.status === status)).map((r) => normalizeCase(clone(r.c)));
    },
    async createCase(body) {
      await wait();
      const rec = newCase(body);
      const turn = makeTurn(rec);
      record(rec, rec.c.memo || '(질문부터 받을게요)', {}, turn);
      return { case: normalizeCase(clone(rec.c)), turn: normalizeTurn(turn) };
    },
    async getCase(id) {
      await wait();
      const rec = find(id);
      const latest = makeTurn(rec);
      const cur = rec.verdicts.find((v) => !v.superseded_at) || null;
      return normalizeDetail(clone({
        case: rec.c, current_verdict: cur, verdicts: rec.verdicts, latest_turn: latest, documents: rec.docs,
        handoff: rec.handoff, conversation: rec.conv,
      }));
    },
    async sendMessage(id, msg) {
      await wait();
      const rec = find(id);
      locked(rec);
      advance(rec, msg);
      const turn = makeTurn(rec);
      record(rec, msg.text || labelOf(rec, msg.quick_reply), msg, turn);
      return normalizeTurn(turn);
    },
    async uploadDocument(id, file, facts = null) {
      await wait();
      const rec = find(id);
      locked(rec);
      // 실제 서버처럼 값은 검수 대기 후보로만 저장하고 판정은 그대로 둔다
      const docId = uid('doc');
      const values = Object.entries(facts || {}).map(([k, v]) => ({
        id: uid('val'), document_id: docId, document_version: 1, fact_key: k, value: v, unit: null, status: 'UNVERIFIED',
        reviewer: null, reviewed_at: null, note: null, created_at: nowIso(), updated_at: null,
      }));
      const document = {
        id: docId, filename: file.name || 'document', content_type: file.type || null, size: file.size || 0, sha256: '',
        extracted_facts: { method: values.length ? 'manual' : 'none', candidates: facts || {}, accepted: {} },
        version: 1, values, created_at: nowIso(), updated_at: null,
      };
      rec.docs.push(document);
      const turn = makeTurn(rec);
      record(rec, `서류 올림: ${document.filename}`, {}, turn);
      return { document: clone(document), turn: normalizeTurn(turn), values: clone(values) };
    },
    async applyDocumentValues(id, docId, items) {
      await wait();
      const rec = find(id);
      locked(rec);
      const doc = rec.docs.find((d) => d.id === docId);
      if (!doc) throw new ApiError('서류를 찾을 수 없습니다', { status: 404, kind: 'not_found' });
      for (const it of items) {
        const v = doc.values.find((x) => x.id === it.value_id);
        if (v) Object.assign(v, { status: 'APPLIED', reviewer: it.reviewer, reviewed_at: it.reviewed_at, updated_at: nowIso() });
      }
      advance(rec, { upload: true }); // 시나리오의 '서류 확인' 단계
      const turn = makeTurn(rec);
      record(rec, '서류 값 검수 완료', {}, turn);
      return normalizeTurn(turn);
    },
    async confirm(id) {
      await wait();
      const rec = find(id);
      const t = step(rec).turn;
      if (t.branch !== 'FINAL_REVIEW' || rec.c.status === 'CODE_CONFIRMED')
        throw new ApiError('확정할 수 있는 판정이 아닙니다', { status: 409, kind: 'conflict' });
      const r = t.ui.result;
      const handoff = {
        schema: 'diagnosis-handoff-v1', case_id: id, verdict: { code: r.code, name: r.name, category: r.category, outcome: r.outcome },
        route_guidance: step(rec).confirm.guidance, kb: step(rec).confirm.kb,
      };
      const verdict = {
        version: rec.verdicts.length + 1, result_type: r.result_type, code: r.code, name: r.name, category: r.category, outcome: r.outcome,
        rule_ids: [], kb_version: step(rec).confirm.kb.kb_version, as_of: rec.c.as_of, facts_snapshot: {}, verdict: t.verdict, handoff,
        confirmed_at: nowIso(), superseded_at: null, reopened_at: null, reopen_reason: null,
      };
      rec.verdicts.push(verdict);
      rec.handoff = handoff;
      rec.c.status = 'CODE_CONFIRMED';
      rec.c.summary.status_label = STATUS_LABEL.CODE_CONFIRMED;
      rec.c.summary.next_action = NEXT_ACTION.CODE_CONFIRMED;
      return { case: normalizeCase(clone(rec.c)), verdict: clone(verdict), handoff: clone(handoff), frozen_trace_rows: rec.trace.length };
    },
    async reopen(id, reason) {
      await wait();
      const rec = find(id);
      if (rec.c.status !== 'CODE_CONFIRMED') throw new ApiError('다시 열 수 있는 건이 아닙니다', { status: 409, kind: 'conflict' });
      const v = rec.verdicts.find((x) => !x.superseded_at);
      Object.assign(v, { superseded_at: nowIso(), reopened_at: nowIso(), reopen_reason: reason || null });
      rec.handoff = null;
      rec.c.status = 'DIAGNOSING';
      const turn = makeTurn(rec);
      return { case: normalizeCase(clone(rec.c)), superseded_verdict: clone(v), turn: normalizeTurn(turn) };
    },
    async trace(id) {
      await wait();
      const rec = find(id);
      return clone({
        case_id: id,
        sessions: [{ session_id: rec.session, as_of: rec.c.as_of, kb_version: 'mock', table_versions: {}, facts: [], turns: rec.trace }],
        verdicts: rec.verdicts,
      });
    },
  };
}
