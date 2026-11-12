import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import QuestionCard from '../components/QuestionCard.jsx';
import ReviewDialog from '../components/ReviewDialog.jsx';
import Board from '../components/Board.jsx';
import { AutoReadNotes, EvidenceCard, PendingReview, toDocumentValue, UnsupportedCard, unreadReasons } from '../components/BranchCards.jsx';
import { normalizeQuestion, setCatalog } from '../api/normalize.js';

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

  it('할 일(원문과 비교해 검수하기)을 먼저 보이고 값은 접어 둔다', async () => {
    const onReview = vi.fn();
    const { rerender } = render(<PendingReview items={[{ doc, value }]} labels={{ oil_content_pct: '유분' }} onReview={onReview} />);
    expect(screen.getByText(/확인한 값만 판정에 쓰여요/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '원문과 비교해 검수하기' }));
    expect(onReview).toHaveBeenCalled();
    expect(screen.getByText('읽은 값 미리 보기')).toBeInTheDocument();
    rerender(<PendingReview items={[{ doc, value }]} onReview={null} />);
    expect(screen.queryByRole('button', { name: '원문과 비교해 검수하기' })).toBeNull();
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

  it('불검출은 미만 구간으로 보여 준다(읽은 위치는 검수 창에서)', () => {
    const doc = { id: 'd1', filename: 'r.pdf', version: 1 };
    const value = { id: 'v1', fact_key: 'leach_cd', value: { lo: null, hi: 0.01, hi_inc: false }, unit: 'mg/L', status: 'UNVERIFIED', document_version: 1, note: '표 자동 읽기(검수 대기) · 1쪽 표1 3행 3열' };
    render(<PendingReview items={[{ doc, value }]} />);
    expect(screen.getByText(/0.01 mg\/L 미만/)).toBeInTheDocument();
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

describe('서류 값 직접 적기', () => {
  it('요청 항목마다 칸을 보이고, 미만(불검출)은 범위로 보낸다', async () => {
    setCatalog([
      { key: 'leach_pb', label: '납 용출 농도', type: 'number', unit: 'mg/L', parent: null, values: [] },
      { key: 'oil_content_pct', label: '기름성분 함량', type: 'number', unit: '%', parent: null, values: [] },
    ]);
    const onUpload = vi.fn();
    const docs = [{ evidence_type: 'TEST_REPORT', label: '시험성적서', facts: ['leach_pb', 'oil_content_pct'], fact_labels: ['납 용출 농도', '기름성분 함량'] }];
    render(<EvidenceCard docs={docs} onUpload={onUpload} onText={vi.fn()} />);
    await userEvent.click(screen.getByText('파일 없이 서류 값 직접 적기'));
    expect(screen.getByText('mg/L')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('기름성분 함량'), '0.4');
    await userEvent.selectOptions(screen.getByLabelText('납 용출 농도 값 모양'), 'lt');
    await userEvent.type(screen.getByLabelText('납 용출 농도'), '0.01');
    await userEvent.click(screen.getByRole('button', { name: '서류 올리기' }));
    expect(onUpload).toHaveBeenCalledWith(null, { leach_pb: { hi: 0.01, hi_inc: false }, oil_content_pct: 0.4 });
  });

  it('숫자가 아니면 보내지 않고 알려 준다', () => {
    expect(() => toDocumentValue({ key: 'n', label: '납', type: 'number' }, { mode: 'eq', value: '불검출' })).toThrow(/숫자만/);
    expect(toDocumentValue({ key: 'n', type: 'number' }, { mode: 'eq', value: '' })).toBeNull();
    expect(toDocumentValue({ key: 'b', type: 'bool' }, { value: 'false' })).toBe(false);
  });
});

describe('판정 불가에서 이어 가기', () => {
  const cat = [
    { key: 'leach_cd', label: '카드뮴 용출 농도', type: 'number', unit: 'mg/L', parent: null, values: [] },
    { key: 'annex4_code', label: '별표 4 분류번호', type: 'enum', unit: null, parent: null, values: [] },
  ];
  const docs = [{ id: 'd1', extracted_facts: { table_read: { items: [
    { key: 'leach_pb', status: 'FOUND' },
    { key: 'leach_cd', status: 'AMBIGUOUS', note: "카드뮴 용출: 용출·함량 구분과 단위를 모두 확인하지 못함 (원문 표기 'mg/mL')" },
  ] } } }];

  it('못 읽은 이유를 보이고, 남은 값을 칸에 적어 보낸다', async () => {
    setCatalog(cat);
    const onValues = vi.fn();
    const pending = [{ key: 'annex4_code', label: '별표 4 분류번호' }, { key: 'leach_cd', label: '카드뮴 용출 농도' }];
    render(<UnsupportedCard message="지금 자료로는 정할 수 없습니다." pending={pending} unread={unreadReasons(docs)} onValues={onValues} />);
    expect(screen.getAllByText(/원문 표기 'mg\/mL'/).length).toBeGreaterThan(0);
    // 못 읽은 값이 있으면 칸이 바로 열려 있다. 고르는 항목(별표 4 번호)은 칸으로 받지 않는다
    expect(screen.queryByLabelText('별표 4 분류번호')).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText('카드뮴 용출 농도 값 모양'), 'lt');
    await userEvent.type(screen.getByLabelText('카드뮴 용출 농도'), '0.3');
    await userEvent.click(screen.getByRole('button', { name: '값 보내기' }));
    expect(onValues).toHaveBeenCalledWith({ leach_cd: { hi: 0.3, hi_inc: false } });
  });

  it('못 읽은 값이 없으면 "서류 값 적기"로 칸을 연다', async () => {
    setCatalog(cat);
    render(<UnsupportedCard message="m" pending={[{ key: 'leach_cd', label: '카드뮴 용출 농도' }]} onValues={vi.fn()} />);
    expect(screen.queryByLabelText('카드뮴 용출 농도')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '서류 값 적기' }));
    expect(screen.getByLabelText('카드뮴 용출 농도')).toBeInTheDocument();
  });
});

describe('서류 값 검수 창', () => {
  const doc = { id: 'd1', filename: '성적서.pdf', version: 1, extracted_facts: { table_read: { items: [
    { key: 'leach_pb', page: 1, value_raw: '불검출', unit_raw: 'mg/L', quote: 'S-1 | 납(mg/L) | 3.0 이상 | 불검출', cell_ref: { page: 1, table_index: 0, row: 1, col: 3 } },
  ] } } };
  const pb = { id: 'v1', fact_key: 'leach_pb', value: { lo: null, hi: 3, hi_inc: false }, unit: 'mg/L', status: 'UNVERIFIED', document_version: 1 };
  const cu = { id: 'v2', fact_key: 'leach_cu', value: 0.021, unit: 'mg/L', status: 'UNVERIFIED', document_version: 1 };
  const items = [{ doc, value: pb }, { doc, value: cu }];

  it('맞아요·고치기로 확인한 값만 검수 완료로 보낸다', async () => {
    setCatalog([
      { key: 'leach_pb', label: '납 용출 농도', type: 'number', unit: 'mg/L', parent: null, values: [] },
      { key: 'leach_cu', label: '구리 용출 농도', type: 'number', unit: 'mg/L', parent: null, values: [] },
    ]);
    const onApply = vi.fn();
    render(<ReviewDialog items={items} onApply={onApply} onClose={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: '서류 값 검수' })).toBeInTheDocument();
    // 원문 위치와 원문 표기를 보여 준다
    expect(screen.getByText(/원문 '불검출 mg\/L' · 1쪽 표1 2행/)).toBeInTheDocument();
    const done = screen.getByRole('button', { name: '검수 완료' });
    expect(done).toBeDisabled();
    const [okPb] = screen.getAllByRole('button', { name: '맞아요' });
    await userEvent.click(okPb);
    const fixes = screen.getAllByRole('button', { name: '고치기' });
    await userEvent.click(fixes[1]);
    await userEvent.type(screen.getByLabelText('구리 용출 농도 고칠 값'), '0.02');
    await userEvent.click(done);
    expect(onApply).toHaveBeenCalledWith([{ doc, value: pb }, { doc, value: cu, fixed: 0.02 }]);
  });

  it('Esc로 닫는다', async () => {
    const onClose = vi.fn();
    render(<ReviewDialog items={items} onApply={vi.fn()} onClose={onClose} />);
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });
});
