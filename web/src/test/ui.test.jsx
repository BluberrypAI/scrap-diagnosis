import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import QuestionCard from '../components/QuestionCard.jsx';
import Board from '../components/Board.jsx';
import { AutoReadNotes, EvidenceCard, PendingReview } from '../components/BranchCards.jsx';
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

describe('PendingReview', () => {
  const doc = { id: 'd1', filename: 'r.txt', version: 1 };
  const value = { id: 'v1', fact_key: 'oil_content_pct', value: 2, unit: null, status: 'UNVERIFIED', document_version: 1 };

  it('검수 대기 값을 보여 주고, 개발용 버튼은 onApply가 있을 때만', async () => {
    const onApply = vi.fn();
    const { rerender } = render(<PendingReview items={[{ doc, value }]} labels={{ oil_content_pct: '유분' }} onApply={onApply} />);
    expect(screen.getByText('유분')).toBeInTheDocument();
    expect(screen.getByText(/v1 · 검수 대기/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '검수 완료로 적용 (개발용)' }));
    expect(onApply).toHaveBeenCalledWith([{ doc, value }]);
    rerender(<PendingReview items={[{ doc, value }]} onApply={null} />);
    expect(screen.queryByRole('button', { name: /검수 완료로 적용/ })).toBeNull();
  });
});

describe('서류 자동 읽기', () => {
  it('파일 선택은 PDF와 사진을 받고, 직접 연 카드는 닫기 버튼이 있다', () => {
    const onClose = vi.fn();
    render(<EvidenceCard docs={[]} onUpload={vi.fn()} onText={vi.fn()} onClose={onClose} />);
    const input = screen.getByLabelText('서류 파일');
    expect(input.getAttribute('accept')).toMatch(/\.pdf/);
    expect(input.getAttribute('accept')).toMatch(/image\/\*/);
    expect(screen.getByRole('button', { name: '닫기' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '서류가 없어요' })).toBeNull();
  });

  it('불검출 구간과 읽은 위치를 보여 준다', () => {
    const doc = { id: 'd1', filename: 'r.pdf', version: 1 };
    const value = { id: 'v1', fact_key: 'leach_cd', value: { lo: null, hi: 0.01, hi_inc: false }, unit: 'mg/L', status: 'UNVERIFIED', document_version: 1, note: '표 자동 읽기(검수 대기) · 1쪽 표1 3행 3열' };
    render(<PendingReview items={[{ doc, value }]} />);
    expect(screen.getByText(/0.01 mg\/L 미만/)).toBeInTheDocument();
    expect(screen.getByText(/1쪽 표1 3행 3열/)).toBeInTheDocument();
  });

  it('정하지 못한 값만 메모로 보여 준다', () => {
    const docs = [{ id: 'd1', filename: 'scan.png', version: 1, extracted_facts: { table_read: { backend: 'azure-prebuilt-layout', source: 'ocr', items: [
      { key: 'leach_pb', status: 'FOUND' },
      { key: 'leach_cd', status: 'AMBIGUOUS', value_raw: 'ND', note: '불검출이지만 검출한계를 찾지 못함' },
    ], errors: [], warnings: [] } } }];
    render(<AutoReadNotes docs={docs} labels={{ leach_cd: '카드뮴 용출' }} />);
    expect(screen.getByText('카드뮴 용출')).toBeInTheDocument();
    expect(screen.getByText(/검출한계를 찾지 못함/)).toBeInTheDocument();
    expect(screen.queryByText('leach_pb')).toBeNull();
    expect(screen.getByText(/문서 인식\(OCR\)으로 읽음/)).toBeInTheDocument();
  });
});
