import { expect, it } from 'vitest';
import { createMockClient } from '../api/mock/mock.js';
import { setCompanyId } from '../api/company.js';

it('목 API가 PP 문진을 확정까지 돌린다', async () => {
  setCompanyId('co-test');
  const api = createMockClient();
  const { case: c, turn } = await api.createCase({ memo: 'PP 사출 불량품이에요' });
  expect(turn.ui.question.key).toBe('contamination_screen');
  let t = await api.sendMessage(c.id, { quick_reply: { key: 'contamination_screen', kind: 'none_all' } });
  t = await api.sendMessage(c.id, { quick_reply: { key: 'scope_screen', kind: 'none_all' } });
  t = await api.sendMessage(c.id, { quick_reply: { key: 'physical_state', kind: 'value', value: 'solid' } });
  expect(t.branch).toBe('FINAL_REVIEW');
  const d = await api.confirm(c.id);
  expect(d.handoff.route_guidance.action).toBe('RECOMMEND_ROUTE');
  expect((await api.getCase(c.id)).case.status).toBe('CODE_CONFIRMED');
});

it('목 API: 서류 값은 검수 대기 후보로 저장되고 적용해야 반영된다', async () => {
  setCompanyId('co-test');
  const api = createMockClient();
  const { case: c, turn } = await api.createCase({ memo: 'PP 사출 불량품이에요' });
  const up = await api.uploadDocument(c.id, { name: 'r.txt' }, { oil_content_pct: 2 });
  expect(up.turn.branch).toBe(turn.branch);
  expect(up.values.map((v) => [v.fact_key, v.status])).toEqual([['oil_content_pct', 'UNVERIFIED']]);
  await api.applyDocumentValues(c.id, up.document.id, [
    { value_id: up.values[0].id, document_version: 1, reviewer: 'dev', reviewed_at: new Date().toISOString() },
  ]);
  const d = await api.getCase(c.id);
  expect(d.documents[0].values[0].status).toBe('APPLIED');
});
