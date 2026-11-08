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
