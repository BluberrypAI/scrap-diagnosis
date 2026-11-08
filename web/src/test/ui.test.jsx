import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import QuestionCard from '../components/QuestionCard.jsx';
import Board from '../components/Board.jsx';
import { normalizeQuestion } from '../api/normalize.js';

const q = (o) => normalizeQuestion({ unit: 'fact', facts: [o.key], text: '질문', ...o });

describe('QuestionCard', () => {
  it('choice: 선택지는 kind=value와 value를 보낸다', async () => {
    const onSend = vi.fn();
    render(<QuestionCard question={q({ key: 'physical_state', input: 'choice', options: [{ label: '고체', value: 'solid', kind: 'value' }, { label: '모름', value: null, kind: 'unknown' }] })} onSend={onSend} />);
    await userEvent.click(screen.getByRole('button', { name: '고체' }));
    expect(onSend).toHaveBeenLastCalledWith({ key: 'physical_state', kind: 'value', value: 'solid' }, '고체');
    await userEvent.click(screen.getByRole('button', { name: '모름' }));
    expect(onSend).toHaveBeenLastCalledWith({ key: 'physical_state', kind: 'unknown' }, '모름');
  });

  it('group: none_all / expand는 value 없이 보낸다', async () => {
    const onSend = vi.fn();
    render(<QuestionCard question={q({ key: 'contamination_screen', unit: 'group', input: 'group', items: [{ key: 'a', label: '항목A' }],
      options: [{ label: '모두 해당 없음', value: { a: false }, kind: 'none_all' }, { label: '해당 있음', value: null, kind: 'expand' }] })} onSend={onSend} />);
    await userEvent.click(screen.getByRole('button', { name: '모두 해당 없음' }));
    expect(onSend).toHaveBeenLastCalledWith({ key: 'contamination_screen', kind: 'none_all' }, '모두 해당 없음');
  });

  it('number: 구간 버튼은 NumRange, 직접 입력은 숫자를 보낸다', async () => {
    const onSend = vi.fn();
    const range = { hi: 5, hi_inc: false };
    render(<QuestionCard question={q({ key: 'oil_content_pct', input: 'number', value_type: 'number', allow_free_number: true,
      options: [{ label: '5% 미만', value: range, kind: 'value' }] })} onSend={onSend} />);
    await userEvent.click(screen.getByRole('button', { name: '5% 미만' }));
    expect(onSend).toHaveBeenLastCalledWith({ key: 'oil_content_pct', kind: 'value', value: range }, '5% 미만');
    await userEvent.type(screen.getByLabelText('정확한 값'), '2');
    await userEvent.click(screen.getByRole('button', { name: '입력' }));
    expect(onSend).toHaveBeenLastCalledWith({ key: 'oil_content_pct', kind: 'value', value: 2 }, '2');
  });
});

describe('Board', () => {
  it('되돌리기는 retract를 보낸다', async () => {
    const onReply = vi.fn();
    const board = { facts: [{ key: 'material', label: '소재', value: 'pp', value_label: 'PP', status: 'CLAIMED', source_type: 'UTTERANCE', source_label: '말함', editable: true, edit: null }],
      pending: [], progress: null, candidates_count: 3, top_candidates: [], documents_needed: [] };
    render(<Board board={board} onReply={onReply} />);
    await userEvent.click(screen.getByRole('button', { name: '되돌리기' }));
    expect(onReply).toHaveBeenCalledWith({ key: 'material', kind: 'retract' }, expect.any(String));
  });
});
