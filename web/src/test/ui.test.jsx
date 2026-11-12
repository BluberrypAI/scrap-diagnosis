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
  const at = (row) => ({ page: 1, table_index: 0, row, col: 3 });
  const doc = { id: 'd1', filename: '성적서.pdf', version: 1, extracted_facts: { table_read: { items: [
    { key: 'leach_tce', status: 'FOUND', page: 1, item_raw: 'TCE(mg/L)', value_raw: '불검출', unit_raw: 'mg/L', below_detection_limit: true, detection_limit_basis: 'limit_column', cell_ref: at(9) },
    { key: 'leach_pb', status: 'FOUND', page: 1, item_raw: '납(mg/L)', value_raw: '불검출', unit_raw: 'mg/L', below_detection_limit: true, detection_limit_basis: 'limit_column', cell_ref: at(1) },
    { key: 'leach_cu', status: 'FOUND', page: 1, item_raw: '구리(mg/L)', value_raw: '0.021', unit_raw: 'mg/L', cell_ref: at(2) },
    { key: 'leach_cd', status: 'AMBIGUOUS', page: 1, item_raw: '카드뮴(mg/mL)', value_raw: '불검출', unit_raw: 'mg/mL', cell_ref: at(3), note: '단위를 확인하지 못함' },
  ] } } };
  const v = (id, key, value) => ({ id, fact_key: key, value, unit: 'mg/L', status: 'UNVERIFIED', document_version: 1 });
  const tce = v('v9', 'leach_tce', { lo: null, hi: 0.3, hi_inc: false });
  const pb = v('v1', 'leach_pb', { lo: null, hi: 3, hi_inc: false });
  const cu = v('v2', 'leach_cu', 0.021);
  const items = [{ doc, value: tce }, { doc, value: pb }, { doc, value: cu }];
  const cat = ['leach_tce:트리클로로에틸렌 용출 농도', 'leach_pb:납 용출 농도', 'leach_cu:구리 용출 농도', 'leach_cd:카드뮴 용출 농도']
    .map((x) => { const [key, label] = x.split(':'); return { key, label, type: 'number', unit: 'mg/L', parent: null, values: [] }; });

  it('원문 순서로 놓고, 원문 항목 이름과 불검출을 그대로 보여 준다', () => {
    setCatalog(cat);
    render(<ReviewDialog items={items} docs={[doc]} onApply={vi.fn()} onClose={vi.fn()} />);
    const labels = [...document.querySelectorAll('.review-item-label')].map((e) => e.textContent);
    expect(labels).toEqual(['원문 ‘납(mg/L)’', '원문 ‘구리(mg/L)’', '원문 ‘카드뮴(mg/mL)’', '원문 ‘TCE(mg/L)’']);
    expect(screen.getByText('→ 트리클로로에틸렌 용출 농도')).toBeInTheDocument();
    expect(screen.getAllByText('불검출 (mg/L)').length).toBe(2);
    expect(screen.getByText(/판정에는 ‘3 mg\/L 미만’으로 써요/)).toBeInTheDocument();
  });

  it('단위가 달라 못 읽은 값은 이유를 알리고, 적은 값은 항목 키로 보낸다', async () => {
    setCatalog(cat);
    const onApply = vi.fn();
    render(<ReviewDialog items={items} docs={[doc]} onApply={onApply} onClose={vi.fn()} />);
    expect(screen.getByText('자동으로 못 읽음')).toBeInTheDocument();
    expect(screen.getByText(/원문 단위가 'mg\/mL'로 적혀 있어요\. 이 항목은 mg\/L 기준/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('카드뮴 용출 농도 원문 값 값 모양'), 'lt');
    await userEvent.type(screen.getByLabelText('카드뮴 용출 농도 원문 값'), '0.3');
    await userEvent.click(screen.getByRole('button', { name: '읽은 값 모두 맞아요' }));
    const fixes = screen.getAllByRole('button', { name: '고치기' });
    await userEvent.click(fixes[1]); // 구리(원문 순서 두 번째)
    await userEvent.type(screen.getByLabelText('구리 용출 농도 고칠 값'), '0.02');
    await userEvent.click(screen.getByRole('button', { name: '검수 완료' }));
    const sent = onApply.mock.calls[0][0];
    expect(sent).toContainEqual({ doc, value: pb });
    expect(sent).toContainEqual({ doc, value: cu, fixed: 0.02 });
    expect(sent).toContainEqual({ doc, factKey: 'leach_cd', fixed: { hi: 0.3, hi_inc: false } });
    expect(sent).toHaveLength(4);
  });

  it('Esc로 닫는다', async () => {
    const onClose = vi.fn();
    render(<ReviewDialog items={items} docs={[doc]} onApply={vi.fn()} onClose={onClose} />);
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });
});
