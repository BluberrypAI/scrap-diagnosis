// 목 API 예시 데이터(src/api/mock/fixtures/*.json)를 만든다: `npm run fixtures`
// 형식은 docs/ui/ui-contract.md(ui-v1)를 그대로 따른다. 만들어진 JSON은 계약 예시로도 쓴다.
// 문구·선택지·근거는 실제 백엔드(data/real, LLM off)에서 받은 응답을 옮겼다.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'api', 'mock', 'fixtures');
const AT = '2026-11-08T21:59:32+09:00';

// ---- 사실 카탈로그(일부, data/real/facts_catalog.yaml) ------------------------------------
const PLASTIC = {
  pp: 'PP(폴리프로필렌)', pe: 'PE(폴리에틸렌)', pet: 'PET', ps: 'PS(폴리스티렌, 발포 아님)', abs: 'ABS 수지',
  phenol_resin: '페놀수지', other_resin: '그 밖의 합성수지(PC, 나일론 등)', pvc: 'PVC(염화비닐)',
  pu_foam: '폴리우레탄폼', eps: '발포합성수지(스티로폼)', plastic_packaging: '플라스틱 포장재',
  fishing_net: '폐어망', aqua_buoy: '양식용 부자', rubber: '합성고무',
};
const ACID = {
  hcl: '폐염산', h2so4: '폐황산', hno3: '폐질산', hf: '폐불산', acid_lcd_semi: 'LCD·반도체 공정 폐산',
  acid_other: '그 밖의 폐산', caustic_solution: '폐가성소다수(수산화나트륨 수용액)', ammonia_solution: '폐암모니아수',
  naoh_solid: '고체 수산화나트륨', koh_solid: '고체 수산화칼륨', alkali_other: '그 밖의 폐알칼리(액체)',
};
const SLUDGE = {
  sludge_ww_pulp_paper: '펄프·제지 폐수처리 오니', sludge_ww_stone: '석재·골재 생산 폐수처리 오니',
  sludge_ww_organic: '그 밖의 폐수처리 오니(유기성)', sludge_ww_inorganic: '그 밖의 폐수처리 오니(무기성)',
  sludge_ww_unknown: '폐수처리 오니(유기성·무기성 모름)', sludge_proc_pulp_paper: '펄프·제지 공정 오니',
  sludge_proc_glass_etching: '유리식각 공정 오니', sludge_proc_silicon: '실리콘 (제조)공정 오니',
};

/** GET /catalog/facts 응답(ui-contract §6). 내부 사실(annex4_code)은 넣지 않는다. */
const CATALOG = [
  { key: 'material_group', label: '소재 분류', type: 'enum', unit: null, parent: null, values: {
    plastic: '플라스틱·고무', metal: '금속', slag: '광재(슬래그)', dust_ash: '분진·소각재', sand: '주물사·폐사·내화물',
    sludge: '오니(슬러지)', oil: '기름', acid_alkali: '산·알칼리', solvent_paint: '용제·페인트',
    wood_paper_fiber: '목재·종이·섬유·유리', catalyst_adsorbent: '촉매·흡착제', product: '제품·복합물',
    special: '여러 소재가 섞여 나누기 어려운 것' } },
  { key: 'material', label: '소재', type: 'enum', unit: null, parent: 'material_group', values: { ...PLASTIC, ...ACID, ...SLUDGE } },
  { key: 'material_fate', label: '이 물질을 어떻게 하는지', type: 'enum', unit: null, parent: null, values: {
    still_used: '제품이나 원료로 계속 쓴다 (아직 필요함)',
    same_process_reinput: '따로 처리하지 않고 같은 공정에 바로 다시 넣는다',
    continuous_feedstock: '따로 처리하지 않고 발생한 시설에서 연속공정으로 다른 제품의 원료로 바로 넣는다',
    released: '내보낸다 (버림·위탁 처리·판매·재활용업체에 넘김 등)' } },
  { key: 'circular_resource_recognized', label: '순환자원 인정서', type: 'bool', unit: null, parent: null, values: null },
  { key: 'law_exclusion', label: '다른 법 적용 대상', type: 'enum', unit: null, parent: null, values: {
    none: '해당 없음', radioactive: '원자력안전법에 따른 방사성 물질 또는 그로 오염된 물질',
    uncontained_gas: '용기에 들어 있지 않은 기체', wastewater: '수질오염방지시설로 들어가거나 공공수역으로 배출되는 폐수',
    livestock_manure: '가축분뇨', sewage_nightsoil: '하수도법에 따른 하수·분뇨' } },
  { key: 'emission_facility', label: '배출시설 허가·신고', type: 'bool', unit: null, parent: null, values: null },
  { key: 'waste_facility', label: '폐기물처리시설 운영', type: 'bool', unit: null, parent: null, values: null },
  { key: 'physical_state', label: '배출 시 상태', type: 'enum', unit: null, parent: null, values: {
    solid: '고체', liquid: '액체(흐름)', semisolid: '반고체·점성·슬러지 상태' } },
  { key: 'ph', label: 'pH', type: 'number', unit: null, parent: null, values: null },
  { key: 'oil_presence', label: '기름 묻음·섞임', type: 'enum', unit: null, parent: null, values: {
    none: '기름이 묻거나 섞이지 않음', present: '기름이 묻어 있거나 섞여 있음' } },
  { key: 'oil_content_pct', label: '기름성분 함량', type: 'number', unit: '%', parent: null, values: null },
  { key: 'sludge_water_pct', label: '수분함량', type: 'number', unit: '%', parent: null, values: null },
  { key: 'pcb_possible', label: 'PCB 사용 기기·절연유 관련', type: 'bool', unit: null, parent: null, values: null },
  { key: 'toxic_chemical_discard', label: '유해화학물질 폐기', type: 'bool', unit: null, parent: null, values: null },
  { key: 'designated_residue', label: '지정폐기물 잔류물', type: 'bool', unit: null, parent: null, values: null },
].map((f) => ({ ...f, values: f.values ? Object.entries(f.values).map(([value, label]) => ({ value, label })) : [] }));
const CAT = Object.fromEntries(CATALOG.map((f) => [f.key, f]));

const HELP = {
  material_group: '원래 무엇이었는지(제품·원료·부품)와 발생 공정으로 고르세요. 플라스틱·고무: PP, PE, PVC, PET, PS, ABS, 우레탄, 스티로폼, 고무 / 산·알칼리: 폐산, 폐알칼리 / 오니(슬러지): 폐수처리 오니, 공정 오니',
  material: '원래 무엇이었는지(제품·원료·부품)와 재질 표시(PP, PE, PVC 등), 발생 공정으로 고르세요. 소재는 분류번호 후보를 정할 뿐이고, 지정폐기물 여부 같은 법적 판단은 뒤의 질문으로 확인합니다.',
  contamination_screen: "대부분의 제조 공정 폐기물은 '모두 해당 없음'입니다. 절삭유·윤활유를 쓰는 공정, 변압기·콘덴서 관련 폐기물, 유해화학물질을 폐기하는 경우에만 '해당하는 게 있어요'를 고르세요.",
  scope_screen: "공정도에서 이 물질이 어디로 가는지 확인하세요. 팔거나 재활용업체에 넘겨도 사업에 필요 없게 된 물질이면 폐기물입니다. 재활용이 가능하다는 이유만으로 폐기물에서 빠지지 않습니다.",
  material_fate: "공정도에서 이 물질이 어디로 가는지 확인하세요. 세척·파쇄·보관 등을 거쳐 다른 곳으로 가면 '내보낸다'입니다.",
  circular_resource_recognized: '기후에너지환경부(유역·지방환경청)가 발급한 순환자원 인정서가 있는지, 유효기간 안인지 확인하세요.',
  physical_state: "배출 시점의 실제 상태로 고르세요. 경계가 애매하면 '모름'으로 답하세요.",
  oil_presence: "사용한 공정에서 절삭유·윤활유를 쓰는지, 겉에 기름막이나 기름 냄새가 있는지 확인하세요. 확실하지 않으면 '모름'으로 답하세요.",
  ph: '시험: 수소이온농도(pH) — 폐기물공정시험기준 ES 06304.1 수소이온농도-유리전극법. 성적서에서 확인할 값: pH 값(0.01 단위), 측정 온도, 시료 채취일',
  oil_content_pct: '시험: 기름성분 — 폐기물공정시험기준 ES 06302.1b 기름성분-중량법. 성적서에서 확인할 값: 기름성분(%), 시료 채취일, 분석기관',
};

const SOURCE_LABEL = { UTTERANCE: '말함', DOCUMENT: '서류', PROFILE: '기업 정보', SCREENING: '묶음 답', DERIVED: '자동', SIMULATION: '시험' };
const valueLabel = (key, v) => {
  const f = CAT[key];
  if (!f) return String(v);
  if (f.type === 'bool') return v ? '예' : '아니오';
  if (f.type === 'number') {
    if (v && typeof v === 'object') return rangeLabel(v, f.unit);
    return `${v}${f.unit || ''}`;
  }
  return f.values.find((o) => o.value === v)?.label ?? String(v);
};
function rangeLabel(r, unit) {
  const u = unit || '';
  if (r.lo != null && r.hi != null) return `${r.lo}${u} ${r.lo_inc ? '이상' : '초과'} ${r.hi}${u} ${r.hi_inc ? '이하' : '미만'}`;
  if (r.hi != null) return `${r.hi}${u} ${r.hi_inc ? '이하' : '미만'}`;
  return `${r.lo}${u} ${r.lo_inc ? '이상' : '초과'}`;
}
function editOf(key) {
  const f = CAT[key];
  if (!f) return null;
  if (f.type === 'number') return { input: 'number', value_type: 'number', unit: f.unit, options: [] };
  if (f.type === 'bool') return { input: 'choice', value_type: 'bool', unit: null, options: [{ label: '예', value: true }, { label: '아니오', value: false }] };
  return { input: 'choice', value_type: 'enum', unit: null, options: f.values };
}

/** ui.board.facts[] 한 행 */
function fact(key, value, { status = 'CLAIMED', source = 'UTTERANCE', quote = null, label = null, vlabel = null } = {}) {
  const editable = !['DOCUMENT', 'DERIVED'].includes(source);
  return {
    key, label: label || CAT[key]?.label || key, value, value_label: vlabel || valueLabel(key, value),
    status, source_type: source, source_label: SOURCE_LABEL[source], quote, recorded_at: AT,
    editable, edit: editable ? editOf(key) : null,
  };
}
const screened = (key, value) => fact(key, value, { source: 'SCREENING' });
const PROFILE_FACT = fact('emission_facility', true, { source: 'PROFILE' });

// ---- 질문 -------------------------------------------------------------------------------
function qChoice(key, { values = null, input = null, text = null } = {}) {
  const f = CAT[key];
  const opts = f.type === 'bool'
    ? [{ label: '예', value: true, kind: 'value' }, { label: '아니오', value: false, kind: 'value' }]
    : (values ? Object.entries(values).map(([value, label]) => ({ label, value })) : f.values).map((o) => ({ label: o.label, value: o.value, kind: 'value' }));
  opts.push({ label: '모름', value: null, kind: 'unknown' });
  return {
    key, unit: 'fact', facts: [key], options: opts,
    text: text || QTEXT[key], help: HELP[key] || null,
    input: input || 'choice', value_type: f.type, allow_unknown: true, allow_free_number: false,
    items: [], answered_items: [],
  };
}
const QTEXT = {
  material_group: '어떤 종류의 폐기물인가요? 가장 가까운 분류를 골라 주세요.',
  material: '어떤 소재(물질)인가요?',
  physical_state: '배출할 때 이 폐기물의 상태는?',
  material_fate: '이 물질을 어떻게 하나요?',
  circular_resource_recognized: '이 물질에 대해 순환자원 인정서를 받았나요?',
  oil_presence: '이 폐기물에 기름(윤활유·절삭유·작동유 등)이 묻어 있거나 섞여 있나요?',
  ph: '이 폐액의 pH(수소이온 농도지수)는 얼마인가요?',
  oil_content_pct: '기름성분 함량은 몇 %(중량)인가요?',
};
function qNumber(key, ranges) {
  const q = qChoice(key);
  q.options = [...ranges.map(([label, value]) => ({ label, value, kind: 'value' })), { label: '모름', value: null, kind: 'unknown' }];
  q.input = 'number';
  q.allow_free_number = true;
  return q;
}
const R = (lo, lo_inc, hi, hi_inc) => ({ lo, lo_inc, hi, hi_inc });
const GROUPS = {
  contamination_screen: { text: '이 폐기물에 해당하는 것이 있나요? (기름·잔류물·PCB·유해화학물질)', none: '모두 해당 없음', expand: '해당하는 게 있어요 / 잘 모르겠어요' },
  scope_screen: { text: '이 물질은 사업장에서 더 쓰지 않아 내보내는 것이고, 아래 어느 것에도 해당하지 않나요?', none: '그렇다 (내보내는 물질이고 해당 없음)', expand: '아니다 / 잘 모르겠다' },
};
const NONE_VALUE = { designated_residue: false, oil_presence: 'none', pcb_possible: false, toxic_chemical_discard: false, material_fate: 'released', circular_resource_recognized: false, law_exclusion: 'none' };
function qGroup(id, members, answered = []) {
  const g = GROUPS[id];
  return {
    key: id, unit: 'group', facts: members,
    options: [
      { label: g.none, value: Object.fromEntries(members.map((k) => [k, NONE_VALUE[k]])), kind: 'none_all' },
      { label: g.expand, value: null, kind: 'expand' },
    ],
    text: g.text, help: HELP[id] || null, input: 'group', value_type: null, allow_unknown: false, allow_free_number: false,
    items: members.map((k) => ({ key: k, label: CAT[k].label })),
    answered_items: answered.map((k) => ({ key: k, label: CAT[k].label, value_label: valueLabel(k, NONE_VALUE[k]) })),
  };
}

// ---- 판정·보드·턴 -----------------------------------------------------------------------
const C = (code, name, outcome = null, rule = null) => ({ code, name, outcome, rule_ids: [rule || `${code || outcome}`] });
const PP_CANDS = [
  C('51-03-01', '폐합성수지류(폐염화비닐수지류는 제외한다)', null, 'pp:GENERAL'),
  C('01-01-02', '폐폴리프로필렌', null, 'pp:S3-1GA-SYNTHETIC_RESIN:01-01-02'),
  C(null, "법에서 폐기물은 '사업에 더 이상 필요 없게 된 물질'입니다. 아직 제품이나 원료로 쓰는 물질은 폐기물이 아닙니다.", 'NOT_WASTE', 'S0-NOT-NEEDED'),
  C(null, '정부에서 순환자원으로 인정받은 물질은 법에서 폐기물로 보지 않습니다.', 'CIRCULAR_RESOURCE', 'S0-CIRCULAR'),
  C(null, '다른 법이 적용되는 물질은 폐기물관리법의 폐기물이 아닙니다.', 'EXCLUDED', 'S0-EXCLUDED'),
  C('06-01-01', '폐유(기름성분 5% 이상)', null, 'pp:S3-OIL'),
];
const fill = (base, n) => Array.from({ length: n }, (_, i) => base[i % base.length]);

function board({ facts, pending = [], asked, cands, count = null, docs = [] }) {
  return {
    facts, pending: pending.map(([key, reason]) => ({ key, label: CAT[key]?.label || key, reason })),
    progress: { questions_asked: asked, max_questions: 12 },
    candidates_count: count ?? cands.length,
    top_candidates: cands.slice(0, 5).map(({ code, name, outcome }) => ({ code, name, outcome })),
    documents_needed: docs,
  };
}
const verdict = (status, cands, extra = {}) => ({
  status, waste_code: null, waste_name: null, category: null, outcome: null, candidates: cands.slice(0, 20),
  conditions: [], rationale: [], failure_reason: null, review: null, ...extra,
});
function turn({ branch, message, status = 'DIAGNOSING', v, question = null, b, docs = [], conflicts = [], result = null, can_confirm = false, replies = [] }) {
  return {
    case_id: '', session_id: '', turn_id: '', branch, sub_branch: null, message,
    verdict: v,
    ui: { can_confirm, suggested_replies: replies, requested_documents: docs, question, board: b, conflicts, result },
    case_status: status,
  };
}
const ask = (q, b, cands, count) => turn({
  branch: 'ASK_FACT', message: q.input === 'group' ? `${q.text}을(를) 알려 주세요.` : q.text,
  v: verdict('IN_PROGRESS', fill(cands, Math.min(count, 20))), question: q, b, replies: [],
});
const cond = (fact, text, satisfied = true, evidence = null) => ({ fact, text, satisfied, evidence });
const REVIEW_NOTE = ' 이 판정은 검토 전 규칙(UNVERIFIED)에 따른 것이라 참고용입니다.';

function final({ code = null, name = null, category, outcome = null, message, conditions, rationale, facts, asked, conclusion, rule }) {
  const cands = [C(code, name || conclusion, outcome, rule)];
  return turn({
    branch: 'FINAL_REVIEW', message, can_confirm: true, replies: ['확정', '다시 확인할게요'],
    v: verdict('CONFIRMABLE', cands, { waste_code: code, waste_name: code ? name : null, category, outcome, conditions, rationale, review: 'UNVERIFIED' }),
    b: board({ facts, asked, cands }),
    result: {
      result_type: code ? 'WASTE_CODE' : 'NO_CODE', code, name: code ? name : null, category, outcome,
      conclusion: code ? `분류번호 ${code} ${name}로 판정됩니다` : conclusion,
      next_step: code ? '확정하면 경로 추천으로 넘어갑니다' : '확정하면 다음 단계에서 어떻게 처리하면 되는지 안내해 드립니다',
      review: 'UNVERIFIED',
    },
  });
}

const GUIDANCE = {
  WASTE_CODE: { action: 'RECOMMEND_ROUTE', summary: '분류번호와 구분(지정/일반)에 맞는 처리 경로와 처리업체를 추천합니다.', notes: ['지정폐기물이면 지정폐기물 처리 허가를 받은 업체만 추천한다.', '판정은 검토 전 규칙(UNVERIFIED)에 따른 참고 판정임을 함께 안내한다.'] },
  NOT_WASTE: { action: 'NO_ROUTE_NEEDED', summary: '폐기물관리법상 폐기물이 아니어서 폐기물 처리 경로가 필요하지 않습니다.', notes: ['나중에 사용을 그만두고 내보내게 되면 다시 문진을 받도록 안내한다.'] },
  CIRCULAR_RESOURCE: { action: 'NO_ROUTE_NEEDED', summary: '순환자원으로 인정받은 물질이라 폐기물로 보지 않습니다. 인정 범위 안에서 거래하면 됩니다.', notes: ['순환자원 인정서의 유효기간과 인정 범위(용도·거래 상대)를 확인하도록 권고한다.', '인정 범위를 벗어나 처리하면 다시 문진을 받도록 안내한다.'] },
};
const KB = (table) => ({ kb_version: '208334c435f08fb3', table_id: table, table_version: '2026.11.0+re-2f1355a' });

const B_ANNEX1 = { id: 'B1', type: 'LAW', ref: '폐기물관리법 시행령 별표 1(지정폐기물의 종류)', excerpt: '지정폐기물의 종류(제3조 관련)' };

// ---- 시나리오 1: PP (+ 폐기물 아님·순환자원 분기) ----------------------------------------
const ppMemoFacts = [
  fact('material_group', 'plastic', { quote: 'PP 사출 불량품' }),
  fact('material', 'pp', { quote: 'PP 사출 불량품' }),
  PROFILE_FACT,
];
const ppGroupFacts = [fact('material_group', 'plastic'), fact('material', 'pp'), PROFILE_FACT];
const contam = ['designated_residue', 'oil_presence', 'pcb_possible', 'toxic_chemical_discard'];
const contamFacts = contam.map((k) => screened(k, NONE_VALUE[k]));
const scope = ['material_fate', 'circular_resource_recognized', 'law_exclusion'];
const scopeFacts = scope.map((k) => screened(k, NONE_VALUE[k]));

const pp = {
  id: 'pp',
  title: 'PP 사출 스크랩 (일반폐기물 · 폐기물 아님 분기)',
  match: ['pp', '폴리프로필렌', '사출', '플라스틱', '합성수지'],
  start: { memo: 's_contam', empty: 's_group' },
  memo_facts: ppMemoFacts,
  steps: {
    s_group: {
      branch_reason: "확정을 막는 미확인 사실 중 'material_group' 선택",
      next: { default: 's_material' },
      turn: ask(qChoice('material_group', { input: 'material_group' }), board({ facts: [PROFILE_FACT], pending: [['material_group', 'MISSING']], asked: 1, cands: PP_CANDS, count: 97 }), PP_CANDS, 97),
    },
    s_material: {
      branch_reason: "확정을 막는 미확인 사실 중 'material' 선택",
      next: { default: 's_contam' },
      turn: ask(qChoice('material', { values: PLASTIC, input: 'material' }), board({ facts: [fact('material_group', 'plastic'), PROFILE_FACT], pending: [['material', 'MISSING']], asked: 2, cands: PP_CANDS, count: 31 }), PP_CANDS, 31),
    },
    s_contam: {
      branch_reason: "확정을 막는 미확인 사실 중 'contamination_screen' 선택",
      score_breakdown: [
        { unit: 'group', key: 'contamination_screen', legal_priority: 3, gain: 0.880197, resolve: 14.903856, cost: 1, focus: 1, score: 2.64059, outcomes: { '모두 해당 없음': 6, '해당하는 게 있어요 / 잘 모르겠어요': 22 } },
        { unit: 'fact', key: 'oil_presence', legal_priority: 3, gain: 0.484909, resolve: 6.2, cost: 1, focus: 1, score: 1.454727, outcomes: { '기름이 묻거나 섞이지 않음': 14, '기름이 묻어 있거나 섞여 있음': 9 } },
      ],
      next: { none_all: 's_scope', expand: 's_oil', default: 's_scope' },
      turn: ask(qGroup('contamination_screen', contam), board({ facts: ppMemoFacts, pending: contam.map((k) => [k, 'MISSING']), asked: 1, cands: PP_CANDS, count: 22 }), PP_CANDS, 22),
    },
    s_oil: {
      branch_reason: "묶음 'contamination_screen'을 펼쳐 'oil_presence' 선택",
      next: { 'value:present': 's_state', default: 's_scope' },
      turn: ask(qChoice('oil_presence'), board({ facts: ppMemoFacts, pending: contam.map((k) => [k, 'MISSING']), asked: 2, cands: PP_CANDS, count: 22 }), PP_CANDS, 22),
    },
    s_scope: {
      branch_reason: "확정을 막는 미확인 사실 중 'scope_screen' 선택",
      next: { none_all: 's_state', expand: 's_fate', default: 's_state' },
      turn: ask(qGroup('scope_screen', scope), board({ facts: [...ppMemoFacts, ...contamFacts], pending: scope.map((k) => [k, 'MISSING']), asked: 2, cands: PP_CANDS, count: 6 }), PP_CANDS, 6),
    },
    s_fate: {
      branch_reason: "묶음 'scope_screen'을 펼쳐 'material_fate' 선택",
      next: { 'value:still_used': 'nw_circ', default: 's_state' },
      turn: ask(qChoice('material_fate'), board({ facts: [...ppMemoFacts, ...contamFacts], pending: [['material_fate', 'MISSING']], asked: 3, cands: PP_CANDS, count: 6 }), PP_CANDS, 6),
    },
    nw_circ: {
      branch_reason: "확정을 막는 미확인 사실 중 'circular_resource_recognized' 선택",
      next: { 'value:true': 'cr_final', default: 'nw_final' },
      turn: ask(qChoice('circular_resource_recognized'), board({ facts: [...ppMemoFacts, ...contamFacts, fact('material_fate', 'still_used')], pending: [['circular_resource_recognized', 'MISSING']], asked: 4, cands: PP_CANDS.slice(2, 4), count: 2 }), PP_CANDS.slice(2, 4), 2),
    },
    s_state: {
      branch_reason: "확정을 막는 미확인 사실 중 'physical_state' 선택",
      next: { default: 's_final' },
      turn: ask(qChoice('physical_state'), board({ facts: [...ppMemoFacts, ...contamFacts, ...scopeFacts], pending: [['physical_state', 'MISSING']], asked: 3, cands: PP_CANDS.slice(0, 2), count: 2 }), PP_CANDS.slice(0, 2), 2),
    },
    s_final: {
      branch_reason: "후보가 하나로 정해짐(pp:GENERAL)",
      next: {},
      confirm: { guidance: GUIDANCE.WASTE_CODE, kb: KB('pp') },
      turn: final({
        code: '51-03-01', name: '폐합성수지류(폐염화비닐수지류는 제외한다)', category: 'GENERAL', rule: 'pp:GENERAL', asked: 3,
        message: '분류번호는 51-03-01 폐합성수지류(폐염화비닐수지류는 제외한다) (사업장일반폐기물)로 판정됩니다. 내용이 맞으면 확정해 주세요.' + REVIEW_NOTE,
        conditions: [cond('material', '소재: PP(폴리프로필렌)'), cond('physical_state', '배출 시 상태: 고체'), cond('oil_presence', '기름 묻음·섞임: 기름이 묻거나 섞이지 않음'), cond('designated_residue', '지정폐기물 잔류물: 아니오'), cond('material_fate', '이 물질을 어떻게 하는지: 내보낸다')],
        rationale: [B_ANNEX1, { id: 'B2', type: 'LAW', ref: '폐기물관리법 시행규칙 별표 4(폐기물의 종류별 세부분류) 51-03-01', excerpt: '51-03-01 폐합성수지류(폐염화비닐수지류는 제외한다)' }],
        facts: [...ppMemoFacts, ...contamFacts, ...scopeFacts, fact('physical_state', 'solid')],
      }),
    },
    nw_final: {
      branch_reason: "코드 없는 결론(S0-NOT-NEEDED)으로 정해짐",
      next: {},
      confirm: { guidance: GUIDANCE.NOT_WASTE, kb: KB('pp') },
      turn: final({
        category: 'OUT_OF_SCOPE', outcome: 'NOT_WASTE', rule: 'S0-NOT-NEEDED', asked: 4,
        conclusion: '폐기물관리법상 폐기물이 아닙니다',
        message: '말씀하신 내용대로라면 아직 사업에 쓰는 물질이라 폐기물관리법상 폐기물이 아닙니다. 내용이 맞으면 확정해 주세요. 확정하시면 다음 단계에서 어떻게 처리하면 되는지 안내해 드립니다.' + REVIEW_NOTE,
        conditions: [cond('material_fate', '이 물질을 어떻게 하는지: 제품이나 원료로 계속 쓴다 (아직 필요함)'), cond('circular_resource_recognized', '순환자원 인정서: 아니오')],
        rationale: [{ id: 'B1', type: 'LAW', ref: '폐기물관리법 제2조제1호', excerpt: '사람의 생활이나 사업활동에 필요하지 아니하게 된 물질을 말한다.' }],
        facts: [...ppMemoFacts, ...contamFacts, fact('material_fate', 'still_used'), fact('circular_resource_recognized', false)],
      }),
    },
    cr_final: {
      branch_reason: "코드 없는 결론(S0-CIRCULAR)으로 정해짐",
      next: {},
      confirm: { guidance: GUIDANCE.CIRCULAR_RESOURCE, kb: KB('pp') },
      turn: final({
        category: 'OUT_OF_SCOPE', outcome: 'CIRCULAR_RESOURCE', rule: 'S0-CIRCULAR', asked: 4,
        conclusion: '순환자원으로 인정받은 물질이라 폐기물로 보지 않습니다',
        message: '순환자원으로 인정받은 물질이라 폐기물로 보지 않습니다. 내용이 맞으면 확정해 주세요. 확정하시면 다음 단계에서 어떻게 처리하면 되는지 안내해 드립니다.' + REVIEW_NOTE,
        conditions: [cond('circular_resource_recognized', '순환자원 인정서: 예')],
        rationale: [{ id: 'B1', type: 'LAW', ref: '순환경제사회 전환 촉진법 제21조제5항', excerpt: '제1항부터 제3항까지의 규정에 따라 기후에너지환경부장관의 인정을 받은 순환자원은 폐기물로 보지 아니한다.' }],
        facts: [...ppMemoFacts, ...contamFacts, fact('material_fate', 'still_used'), fact('circular_resource_recognized', true)],
      }),
    },
  },
};

// ---- 시나리오 2: 도금 라인 폐황산 (서류 요청) --------------------------------------------
const ACID_CANDS = [
  C('02-01-02', '폐황산(폐황산이 포함된 2차폐축전지는 제외한다)', null, 'h2so4:DESIGNATED'),
  C(null, '지정폐기물이 아닌 폐산입니다. 일반폐기물 세부 번호는 담당자 확인이 필요합니다.', 'NO_GENERAL_CODE', 'h2so4:NO_GENERAL'),
  C(null, '다른 법이 적용되는 물질은 폐기물관리법의 폐기물이 아닙니다.', 'EXCLUDED', 'S0-EXCLUDED'),
  C(null, "법에서 폐기물은 '사업에 더 이상 필요 없게 된 물질'입니다.", 'NOT_WASTE', 'S0-NOT-NEEDED'),
];
const acidMemoFacts = [
  fact('material_group', 'acid_alkali', { quote: '도금 라인 폐황산' }),
  fact('material', 'h2so4', { quote: '도금 라인 폐황산' }),
  PROFILE_FACT,
];
const acidContam = ['oil_presence', 'pcb_possible', 'toxic_chemical_discard'];
const acidContamFacts = acidContam.map((k) => screened(k, NONE_VALUE[k]));
const TEST_DOC_PH = { evidence_type: 'TEST_REPORT', label: '시험성적서', facts: ['ph'], fact_labels: ['pH'] };
const phClaim = fact('ph', R(null, true, 2, true));
const acidBase = [...acidMemoFacts, ...acidContamFacts, ...scopeFacts];

const acid = {
  id: 'acid',
  title: '도금 라인 폐황산 (시험성적서 요청)',
  match: ['황산', '폐산', '염산', '도금', '산·알칼리'],
  start: { memo: 'a_contam', empty: 'a_contam' },
  memo_facts: acidMemoFacts,
  steps: {
    a_contam: {
      branch_reason: "확정을 막는 미확인 사실 중 'contamination_screen' 선택",
      next: { default: 'a_scope' },
      turn: ask(qGroup('contamination_screen', acidContam), board({ facts: acidMemoFacts, pending: acidContam.map((k) => [k, 'MISSING']), asked: 1, cands: ACID_CANDS, count: 20 }), ACID_CANDS, 20),
    },
    a_scope: {
      branch_reason: "확정을 막는 미확인 사실 중 'scope_screen' 선택",
      next: { default: 'a_ph' },
      turn: ask(qGroup('scope_screen', scope), board({ facts: [...acidMemoFacts, ...acidContamFacts], pending: scope.map((k) => [k, 'MISSING']), asked: 2, cands: ACID_CANDS, count: 6 }), ACID_CANDS, 6),
    },
    a_ph: {
      branch_reason: "확정을 막는 미확인 사실 중 'ph' 선택",
      next: { default: 'a_evidence' },
      turn: (() => {
        const t = ask(qNumber('ph', [['2 이하', R(null, true, 2, true)], ['2 초과', R(2, false, null, false)]]),
          board({ facts: acidBase, pending: [['ph', 'MISSING']], asked: 3, cands: ACID_CANDS.slice(0, 2), docs: [TEST_DOC_PH] }), ACID_CANDS.slice(0, 2), 2);
        t.verdict.conditions = [cond('ph', 'pH: 2 이하', null, 'TEST_REPORT'), cond('material', '소재: 폐황산')];
        return t;
      })(),
    },
    a_evidence: {
      branch_reason: "pH는 시험성적서로만 확정할 수 있어 서류를 요청",
      next: { upload: 'a_final', refuse: 'a_refused', default: 'a_evidence' },
      turn: turn({
        branch: 'REQUEST_EVIDENCE', status: 'NEEDS_INFO',
        message: '확정하려면 서류 확인이 필요합니다. 시험성적서를 올려 주세요. (확인할 항목: pH)',
        v: verdict('NEEDS_EVIDENCE', ACID_CANDS.slice(0, 2), { conditions: [cond('ph', 'pH: 2 이하', null, 'TEST_REPORT'), cond('material', '소재: 폐황산')] }),
        docs: [TEST_DOC_PH], replies: ['서류가 없어요'],
        b: board({ facts: [...acidBase, phClaim], pending: [['ph', 'NEEDS_EVIDENCE']], asked: 3, cands: ACID_CANDS.slice(0, 2), docs: [TEST_DOC_PH] }),
      }),
    },
    a_refused: {
      branch_reason: '증빙 거부 → 결론을 낼 수 없음',
      next: { upload: 'a_final', default: 'a_refused' },
      turn: turn({
        branch: 'UNSUPPORTED', status: 'NEEDS_INFO',
        message: '시험성적서가 없으면 pH를 확인할 수 없어 분류번호를 정할 수 없습니다. 성적서를 받으면 이 건에 올려 이어서 진행해 주세요.',
        v: verdict('UNDETERMINABLE', ACID_CANDS.slice(0, 2), { failure_reason: 'EVIDENCE_REFUSED' }),
        b: board({ facts: [...acidBase, phClaim], pending: [['ph', 'NEEDS_EVIDENCE']], asked: 3, cands: ACID_CANDS.slice(0, 2), docs: [TEST_DOC_PH] }),
      }),
    },
    a_final: {
      branch_reason: '서류로 pH 확인 → 후보 하나(h2so4:DESIGNATED)',
      next: {},
      confirm: { guidance: GUIDANCE.WASTE_CODE, kb: KB('h2so4') },
      turn: final({
        code: '02-01-02', name: '폐황산(폐황산이 포함된 2차폐축전지는 제외한다)', category: 'DESIGNATED', rule: 'h2so4:DESIGNATED', asked: 3,
        message: '분류번호는 02-01-02 폐황산(폐황산이 포함된 2차폐축전지는 제외한다) (지정폐기물)로 판정됩니다. 내용이 맞으면 확정해 주세요.' + REVIEW_NOTE,
        conditions: [cond('material', '소재: 폐황산'), cond('ph', 'pH: 2 이하', true, 'TEST_REPORT')],
        rationale: [
          { id: 'B1', type: 'LAW', ref: '폐기물관리법 시행령 별표 1 제2호가목 폐산', excerpt: '액체상태의 폐기물로서 수소이온 농도지수가 2.0 이하인 것으로 한정한다.' },
          { id: 'B2', type: 'LAW', ref: '폐기물관리법 시행규칙 별표 4(폐기물의 종류별 세부분류) 02-01-02', excerpt: '02-01-02 폐황산(폐황산이 포함된 2차폐축전지는 제외한다)' },
        ],
        facts: [...acidBase, fact('ph', 1.2, { status: 'EVIDENCED', source: 'DOCUMENT', quote: '수소이온농도(pH) 1.2' })],
      }),
    },
  },
};

// ---- 시나리오 3: 폐수처리 오니 (진술과 서류의 충돌) --------------------------------------
const SLUDGE_CANDS = [
  C('51-01-08', '그 밖의 폐수처리오니', null, 'sludge_ww_organic:GENERAL'),
  C('01-02-01', '폐수처리오니', null, 'sludge_ww_organic:DESIGNATED'),
  C('06-01-01', '폐유(기름성분 5% 이상)', null, 'sludge_ww_organic:OIL'),
];
const sludgeMemoFacts = [fact('material_group', 'sludge', { quote: '폐수처리 오니' }), PROFILE_FACT];
const sludgeBase = [...sludgeMemoFacts.slice(0, 1), fact('material', 'sludge_ww_organic'), PROFILE_FACT];
const TEST_DOC_OIL = { evidence_type: 'TEST_REPORT', label: '시험성적서', facts: ['oil_content_pct'], fact_labels: ['기름성분 함량'] };
const oilClaim = fact('oil_content_pct', 8, { quote: '기름이 8% 정도' });
const conflictTurn = turn({
  branch: 'RESOLVE_CONFLICT', status: 'DIAGNOSING',
  message: '말씀하신 기름성분 함량(8%)과 시험성적서의 값(2%)이 다릅니다. 어느 쪽이 맞는지 알려 주세요.',
  v: verdict('IN_PROGRESS', SLUDGE_CANDS),
  b: board({ facts: [...sludgeBase, fact('oil_content_pct', 2.0, { status: 'EVIDENCED', source: 'DOCUMENT', quote: '기름성분 2.0 %' })], pending: [['oil_content_pct', 'NEEDS_EVIDENCE']], asked: 2, cands: SLUDGE_CANDS }),
  conflicts: [{
    kind: 'CLAIM_VS_EVIDENCE', fact: 'oil_content_pct', label: '기름성분 함량',
    claimed: 8, claimed_label: '8%', evidenced: 2.0, evidenced_label: '2%', document_id: 'doc-sludge-1',
    choices: [
      { label: '서류 값(2%)이 맞아요', quick_reply: { key: 'oil_content_pct', kind: 'value', value: 2.0 } },
      { label: '서류가 잘못됐어요(새 서류 올리기)', action: 'UPLOAD' },
    ],
  }],
});

const sludge = {
  id: 'sludge',
  title: '폐수처리 오니 (진술·서류 충돌)',
  match: ['오니', '슬러지', '폐수'],
  start: { memo: 'c_material', empty: 'c_material' },
  memo_facts: sludgeMemoFacts,
  steps: {
    c_material: {
      branch_reason: "확정을 막는 미확인 사실 중 'material' 선택",
      next: { default: 'c_oil' },
      turn: ask(qChoice('material', { values: SLUDGE, input: 'material' }), board({ facts: sludgeMemoFacts, pending: [['material', 'MISSING']], asked: 1, cands: SLUDGE_CANDS, count: 14 }), SLUDGE_CANDS, 14),
    },
    c_oil: {
      branch_reason: "확정을 막는 미확인 사실 중 'oil_content_pct' 선택",
      next: { default: 'c_evidence' },
      turn: ask(qNumber('oil_content_pct', [['5% 미만', R(null, true, 5, false)], ['5% 이상', R(5, true, null, false)]]),
        board({ facts: sludgeBase, pending: [['oil_content_pct', 'MISSING']], asked: 2, cands: SLUDGE_CANDS, docs: [TEST_DOC_OIL] }), SLUDGE_CANDS, 3),
    },
    c_evidence: {
      branch_reason: '기름성분 함량은 시험성적서로 확인해야 해 서류를 요청',
      next: { upload: 'c_conflict', refuse: 'c_refused', default: 'c_evidence' },
      turn: turn({
        branch: 'REQUEST_EVIDENCE', status: 'NEEDS_INFO',
        message: '확정하려면 서류 확인이 필요합니다. 시험성적서를 올려 주세요. (확인할 항목: 기름성분 함량)',
        v: verdict('NEEDS_EVIDENCE', SLUDGE_CANDS), docs: [TEST_DOC_OIL], replies: ['서류가 없어요'],
        b: board({ facts: [...sludgeBase, oilClaim], pending: [['oil_content_pct', 'NEEDS_EVIDENCE']], asked: 2, cands: SLUDGE_CANDS, docs: [TEST_DOC_OIL] }),
      }),
    },
    c_refused: {
      branch_reason: '증빙 거부 → 결론을 낼 수 없음',
      next: { upload: 'c_conflict', default: 'c_refused' },
      turn: turn({
        branch: 'UNSUPPORTED', status: 'NEEDS_INFO',
        message: '기름성분 함량을 서류로 확인할 수 없어 분류번호를 정할 수 없습니다. 시험성적서를 받으면 이어서 진행해 주세요.',
        v: verdict('UNDETERMINABLE', SLUDGE_CANDS, { failure_reason: 'EVIDENCE_REFUSED' }),
        b: board({ facts: [...sludgeBase, oilClaim], pending: [['oil_content_pct', 'NEEDS_EVIDENCE']], asked: 2, cands: SLUDGE_CANDS, docs: [TEST_DOC_OIL] }),
      }),
    },
    c_conflict: {
      branch_reason: "진술(8)과 서류(2.0)가 다름 — oil_content_pct",
      next: { upload: 'c_final', default: 'c_final' },
      turn: conflictTurn,
    },
    c_final: {
      branch_reason: '충돌 해소 → 후보 하나(sludge_ww_organic:GENERAL)',
      next: {},
      confirm: { guidance: GUIDANCE.WASTE_CODE, kb: KB('sludge_ww_organic') },
      turn: final({
        code: '51-01-08', name: '그 밖의 폐수처리오니', category: 'GENERAL', rule: 'sludge_ww_organic:GENERAL', asked: 2,
        message: '분류번호는 51-01-08 그 밖의 폐수처리오니 (사업장일반폐기물)로 판정됩니다. 내용이 맞으면 확정해 주세요.' + REVIEW_NOTE,
        conditions: [cond('material', '소재: 그 밖의 폐수처리 오니(유기성)'), cond('oil_content_pct', '기름성분 함량: 5% 미만', true, 'TEST_REPORT')],
        rationale: [B_ANNEX1, { id: 'B2', type: 'LAW', ref: '폐기물관리법 시행규칙 별표 4(폐기물의 종류별 세부분류) 51-01-08', excerpt: '51-01-08 그 밖의 폐수처리오니' }],
        facts: [...sludgeBase, fact('oil_content_pct', 2.0, { status: 'EVIDENCED', source: 'DOCUMENT', quote: '기름성분 2.0 %' })],
      }),
    },
  },
};

// ---- 예시(시나리오 밖): 후보 0개 충돌, 오류 응답 ----------------------------------------
const examples = {
  conflict_no_candidate: (() => {
    const t = turn({
      branch: 'RESOLVE_CONFLICT', message: '답하신 내용으로는 맞는 분류가 없습니다. 아래 항목을 다시 확인해 주세요.',
      v: verdict('IN_PROGRESS', []),
      b: board({ facts: [fact('material_group', 'plastic'), fact('material', 'pp'), fact('physical_state', 'liquid'), PROFILE_FACT], asked: 3, cands: [], count: 0 }),
      conflicts: [{
        kind: 'NO_CANDIDATE', fact: 'physical_state', facts: ['physical_state', 'material'], label: '배출 시 상태',
        choices: [
          { label: '배출 시 상태 다시 답하기', action: 'EDIT_FACT', key: 'physical_state' },
          { label: '소재 다시 답하기', action: 'EDIT_FACT', key: 'material' },
        ],
      }],
    });
    return t;
  })(),
  errors: {
    stale_409: { status: 409, body: { detail: { message: '다른 요청이 같은 문진을 먼저 갱신했습니다. 다시 시도하세요' } } },
    confirm_409: { status: 409, body: { detail: { message: '확정할 수 있는 판정이 아닙니다', case_status: 'DIAGNOSING' } } },
    unauthorized_401: { status: 401, body: { detail: { message: 'X-Company-Id 헤더가 필요합니다' } } },
    unsupported_415: { status: 415, body: { detail: { message: '지원하지 않는 파일 형식입니다(.pdf/.txt/.md)' } } },
    validation_422: { status: 422, body: { detail: [{ type: 'missing', loc: ['body', 'text'], msg: 'Field required' }] } },
  },
};

const profileOptions = {
  facilities: [
    { value: 'air_emission', label: '대기 배출시설' },
    { value: 'water_emission', label: '수질 배출시설' },
    { value: 'noise_vibration', label: '소음·진동 배출시설' },
    { value: 'waste_treatment', label: '폐기물 처리시설' },
    { value: 'none', label: '해당 없음' },
  ],
};

mkdirSync(OUT, { recursive: true });
const write = (name, data) => writeFileSync(join(OUT, name), JSON.stringify(data, null, 2) + '\n', 'utf8');
write('catalog-facts.json', CATALOG);
write('profile-options.json', profileOptions);
write('scenario-pp.json', pp);
write('scenario-acid.json', acid);
write('scenario-sludge.json', sludge);
write('examples.json', examples);
console.log('fixtures →', OUT);
