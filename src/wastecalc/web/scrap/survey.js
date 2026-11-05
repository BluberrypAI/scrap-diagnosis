/* SCRAP 문진 화면 — 엔진 연결판.
 * SCRAP.html(Figma Make 내보내기)의 문진 경로(#/wastes/<id>/survey)에서만 동작한다.
 * 화면 구조·클래스 이름은 디자인의 문진 화면(L3-Survey)을 따르고, 질문·보기·후보 수·근거·재활용 유형은
 * 모두 엔진 API(/api/session …)의 결과를 그대로 보여 준다. 판정은 화면에서 하지 않는다.
 */
(function () {
  if (!window.__ENGINE_SURVEY) return;
  const root = document.getElementById('root');
  const wasteId = (window.__route().path.split('/')[2]) || 'new';
  const STAGE_INDEX = {S0: 0, S1: 1, S2: 2, S3: 3, S4: 4, S5: 5, S6: 6};
  const storageKey = 'wastecalc:survey:' + wasteId;
  const S = {
    phase: 'intake', text: '', proposed: [], view: null, sel: null, num: '', group: null,
    overlay: null, berry: '어떤 폐기물인지 편하게 적어 주세요', saving: false, llm: false, asOf: '', err: '',
    edit: null, loading: true, saveFailed: false, storageNote: '',
    // 묶음 질문 상태: one_of 선택, 항목별 답, 성적서 유무와 입력값
    gsel: null, gvals: {}, greport: null, gnums: {},
    siteFacts: [], lastCount: null,
  };
  const SITE_KEY = 'wastecalc:site-profile';
  const loadSite = () => { try { return JSON.parse(localStorage.getItem(SITE_KEY) || '{}'); } catch (_) { return {}; } };
  function rememberSite() {
    // 사업장 공통 사실(배출시설 등)은 폐기물마다 다시 묻지 않도록 이 브라우저에 사업장 정보로 기억한다.
    if (!S.view || !S.siteFacts.length) return;
    const site = loadSite();
    (S.view.answered || []).forEach(a => { if (S.siteFacts.includes(a.fact) && a.value !== 'UNKNOWN') site[a.fact] = a.value; });
    try { localStorage.setItem(SITE_KEY, JSON.stringify(site)); } catch (_) {}
  }

  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const arrow = '<span aria-hidden="true">→</span>';

  async function api(path, body) {
    const r = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'Content-Type': 'application/json'},
      body: body ? JSON.stringify(body) : undefined});
    const j = await r.json();
    if (!r.ok) { const e = new Error(j.detail || r.statusText); e.status = r.status; throw e; }
    return j;
  }
  function say(msg, ms) {
    S.berry = msg; render();
    if (msg && ms) setTimeout(() => { if (S.berry === msg) { S.berry = null; render(); } }, ms);
  }
  async function run(fn) {
    S.err = '';
    try { await fn(); } catch (e) { S.err = String(e.message || e); render(); }
  }

  // ---------------------------------------------------------------- 엔진 호출
  function rememberSession() {
    try { localStorage.setItem(storageKey, S.view.session_id); S.storageNote = ''; }
    catch (_) { S.storageNote = '문진은 서버에 저장됐지만 이 브라우저에 이어가기 정보를 기록하지 못했어요.'; }
  }
  async function saveView(fn) {
    if (S.saving) return;
    S.saving = true; S.saveFailed = false; render();
    try {
      S.view = await fn(); rememberSession(); rememberSite();
      S.sel = null; S.group = null; S.num = ''; S.edit = null;
      S.gsel = null; S.gvals = {}; S.greport = null; S.gnums = {};
      afterView('답변을 저장했어요. 필요한 조건을 이어서 확인할게요');
    } catch (e) { S.saveFailed = true; throw e; }
    finally { S.saving = false; render(); }
  }
  async function startSession(answers) {
    // 사업장 정보(이전 문진에서 확인한 배출시설 등)를 먼저 채우고, 이번 설명에서 읽은 값이 있으면 그것을 쓴다.
    const site = loadSite();
    const reused = Object.keys(site).filter(f => S.siteFacts.includes(f) && !(f in answers));
    await saveView(() => api('/api/session', {answers: {...site, ...answers}, strict: true, waste_id: wasteId, include_reporting: true}));
    if (reused.length) say(`사업장 정보 ${reused.length}개는 저장된 값을 썼어요. 오른쪽 '입력한 답'에서 고칠 수 있어요`, 3500);
  }
  async function sendAnswer(fact, value) {
    await saveView(() => api(`/api/session/${S.view.session_id}/answer`, {fact, value}));
  }
  async function sendAnswers(answers) {
    await saveView(() => api(`/api/session/${S.view.session_id}/answers`, {answers}));
  }
  async function undo() {
    await saveView(() => api(`/api/session/${S.view.session_id}/undo`, {}));
  }
  function afterView(msg) {
    const r = S.view.result;
    if (r.next_question) { S.phase = 'question'; say(msg, 1600); return; }
    S.phase = 'result'; S.berry = null; render();
  }
  // ---------------------------------------------------------------- 화면 조각
  function workbar() {
    const r = S.view && S.view.result;
    const s4 = r && (r.decided || []).find(d => d.stage === 'S4');
    const name = s4 ? s4.label : '새 폐기물 문진';
    return `<header class="l3-workbar" data-layer-name="L3-WorkBar">
      <button type="button" data-act="exit"><span>←</span>나가기</button>
      <strong>${esc(name)}</strong>
      <span role="status" class="${S.saving ? 'is-saving' : ''}">${S.loading ? '저장한 문진 확인 중…' : S.saving ? '저장 중...' : S.saveFailed ? '저장 실패 · 다시 시도' : S.view && S.view.saved ? '자동 저장됨' : '문진 시작 전'}</span></header>`;
  }
  function progress() {
    let w = 0;
    if (S.phase === 'question' && S.view) w = ((STAGE_INDEX[S.view.result.stage] || 0) + 0.5) / 7 * 100;
    if (S.phase === 'result' && S.view) {
      const r = S.view.result;
      w = r.assessment_complete ? 100 : (r.decided || []).length / 7 * 100;
    }
    return `<div class="survey-progress-track" role="progressbar" aria-label="판정 단계 진행" aria-valuenow="${Math.round(w)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${w}%"></span></div>`;
  }
  function berryDock() {
    return `<div class="berry-dock" data-speaking="${S.berry ? 'true' : 'false'}" data-layer-name="Agent-Berry">
      <img src="/scrap-engine/berry.png" alt="에이전트 베리">
      ${S.berry ? `<p class="berry-bubble" role="status"><b>베리</b>${esc(S.berry)}</p>` : ''}</div>`;
  }
  function errLine() { return `${S.err ? `<p class="sv-engine-err" role="alert">${esc(S.err)}</p>` : ''}
    ${S.storageNote ? `<p class="sv-helper">${esc(S.storageNote)}</p>` : ''}`; }

  const statusText = status => ({DETERMINED: '계산 완료', PROVISIONAL: '잠정', FACT_CONFIRMED: '입력 사실 확인',
    NOT_APPLICABLE: '해당 절차 아님', NOT_REQUESTED: '요청 범위 밖', WAITING: '앞선 확인 필요', NEED_INFO: '자료 필요',
    NEED_TEST: '시험 필요', NEED_EXPERT: '기관 확인 필요', OUT_OF_SCOPE: '적용 규칙 미확보'}[status] || '확인 필요');
  function checksView(r) {
    if (!(r.checks || []).length) return '';
    return `<section><h2 class="sv-h2">항목별 확인 결과</h2><dl class="sv-checks">${r.checks.map(c =>
      `<div><dt>${esc(c.title)}<small>${esc(c.label)}</small></dt><dd>${esc(statusText(c.status))}</dd></div>`).join('')}</dl></section>`;
  }
  function resolveView(r) {
    return (r.how_to_resolve || []).length ? `<section><h2 class="sv-h2">확인할 것</h2><ul class="sv-engine-list">${r.how_to_resolve.map(h =>
      `<li><b>${esc(h.question)}</b><p>${esc((h.how_to_check || []).join(' / '))}</p>${h.test ? `<p>시험: ${esc(h.test.item)} — ${esc(h.test.method)}</p>` : ''}</li>`).join('')}</ul></section>` : '';
  }
  function reportingView(r) {
    if (!r.reporting) return '';
    return `<section><h2 class="sv-h2">신고·처리계획 확인</h2>${['general_notice', 'designated_plan'].map(k => {
      const item = r.reporting[k]; if (!item) return '';
      return `<article class="sv-notice"><p><b>${k === 'general_notice' ? '사업장폐기물 배출자 신고' : '지정폐기물 처리계획 확인'} · ${esc(item.label)}</b>
        ${item.provisional ? '<small>사람 검토 전 규칙에 따른 잠정 결과</small>' : ''}</p><p>${esc(item.why || '')}</p>
        ${(item.basis || []).length ? `<button type="button" class="button button-quiet" data-act="law-report" data-key="${k}">근거 조문 보기</button>` : ''}</article>`;
    }).join('')}<p class="sv-helper">${esc(r.reporting.scope)}</p></section>`;
  }

  function questionActions(canBack, ready) {
    return `<button class="button button-quiet" type="button" data-act="back" ${canBack ? '' : 'disabled'}>이전</button>
      ${ready ? `<button class="button button-primary" type="button" data-act="next">다음 ${arrow}</button>`
              : '<span class="survey-guide">답변을 선택하면 다음 단계로 이동할 수 있어요.</span>'}`;
  }

  function answeredList() {
    if (!S.view) return '';
    const answered = S.view.answered || [], reviews = S.view.needs_review || [];
    if (!answered.length && !reviews.length) return '';
    const row = (a, review) => `<li><span>${esc(a.label)}: <b>${esc(a.value_text)}</b>${review ? '<small>앞 답이 바뀌어 재확인이 필요해요</small>' : S.siteFacts.includes(a.fact) ? '<small>사업장 정보 · 다음 문진에도 사용</small>' : ''}</span>
      <button type="button" data-act="edit-fact" data-fact="${esc(a.fact)}">${a.fact === 'code' || a.fact === 'general_group' ? '다시 선택' : review ? '재확인' : '수정'}</button></li>`;
    return `<details class="sv-engine-answered" ${reviews.length ? 'open' : ''}><summary>입력한 답 ${answered.length}개${reviews.length ? ` · 재확인 ${reviews.length}개` : ''}</summary>
      <ul>${reviews.map(a => row(a, true)).join('')}${answered.map(a => row(a, false)).join('')}</ul></details>`;
  }

  async function editFact(fid) {
    if (fid === 'code' || fid === 'general_group') { await sendAnswer(fid, null); return; }
    const q = await api('/api/fact/' + encodeURIComponent(fid));
    const a = [...(S.view.answered || []), ...(S.view.needs_review || [])].find(x => x.fact === fid);
    const val = a && a.value && typeof a.value === 'object' ? a.value.value : a && a.value;
    S.edit = {...q, input: q.choices ? String(q.choices.findIndex(o => JSON.stringify(o.value) === JSON.stringify(val))) : String(val == null ? '' : val)};
    S.err = ''; render();
  }

  function intake() {
    const reading = S.phase === 'reading';
    const examples = ['사출 공장 3번 라인에서 나오는 성형 불량품과 스프루, 런너를 월 2.3톤 정도 버려요',
      '프레스 공장인데 절삭유 묻은 철 칩이 나와요. 대기 배출시설 신고는 돼 있어요.'];
    return `<main class="sv-intake" data-layer-name="Survey-Intake">
      <p class="sv-context">새 폐기물 문진</p>
      <h1>어떤 폐기물인가요?</h1>
      <p class="sv-helper">어떤 공정에서 무엇이 나오는지 편하게 적어 주세요. 적어 주신 만큼 질문이 줄어들어요.</p>
      <textarea class="sv-textarea" rows="5" data-bind="text" placeholder="예) 사출 공장에서 나오는 플라스틱 불량품이에요"
        aria-label="폐기물 설명" ${reading ? 'disabled' : ''}>${esc(S.text)}</textarea>
      <div class="sv-examples"><span>예시</span>${examples.map((e, i) =>
        `<button type="button" data-act="example" data-i="${i}" ${reading ? 'disabled' : ''}>${esc(e)}</button>`).join('')}</div>
      ${S.llm ? '' : '<p class="sv-helper sv-engine-note">지금은 설명에서 답을 읽어오는 기능을 사용할 수 없어요. 질문으로 바로 시작할 수 있어요.</p>'}
      ${errLine()}
      <footer class="survey-actions">
        <button class="button button-quiet" type="button" data-act="plain" ${reading ? 'disabled' : ''}>질문으로 바로 시작</button>
        <button class="button button-primary" type="button" data-act="extract" ${(!S.text.trim() || reading || !S.llm) ? 'disabled' : ''}>
          ${reading ? '읽는 중…' : '베리에게 알려주기'} ${arrow}</button>
      </footer></main>`;
  }
  function confirmView() {
    return `<main class="sv-intake" data-layer-name="Survey-Confirm">
      <p class="sv-context">새 폐기물 문진</p>
      <h1>이렇게 이해했어요</h1>
      <p class="sv-helper">설명에서 확실히 읽힌 것만 골랐어요. 틀린 항목은 체크를 풀어 주세요. 확인하면 남은 질문으로 이어집니다.</p>
      <dl class="sv-cues">${S.proposed.map((p, i) => `<div>
        <dt><label><input type="checkbox" data-act="cue" data-i="${i}" ${p.keep ? 'checked' : ''}> ${esc(p.label)}</label></dt>
        <dd>${esc(p.value_text)}<small class="sv-engine-evidence">“${esc(p.evidence)}”</small></dd></div>`).join('')}</dl>
      ${errLine()}
      <footer class="survey-actions">
        <button class="button button-quiet" type="button" data-act="edit">수정하기</button>
        <button class="button button-primary" type="button" data-act="confirm">맞아요, 문진 시작 ${arrow}</button>
      </footer></main>`;
  }

  function lawBlock(q) {
    if (!q.law || !q.law.length) return '';
    const l = q.law[0];
    const note = l.evidence !== 'LAW' ? ' <small>(법령이 아닌 해설·질의회신 자료)</small>' : '';
    return `<div class="sv-law"><p>${esc(l.cite)}은(는) <strong>“${esc(l.quote)}”</strong>로 정합니다.${note}</p>
      <button type="button" data-act="law-q">근거 조문 보기 ${arrow}</button></div>`;
  }
  function optionsFor(q) {
    const ch = q.choices || [];
    const grouped = ch.some(c => c.group);
    if (grouped && S.group == null) {  // 1단계: 묶음 고르기
      const groups = [];
      ch.forEach(c => { const g = c.group || '모름'; let x = groups.find(y => y.label === g);
        if (!x) { x = {label: g, members: [], value: c.group ? null : c.value}; groups.push(x); } x.members.push(c); });
      return groups.map(g => {
        const rem = g.members.map(m => m.remaining).filter(v => v !== undefined);
        return {key: 'g:' + g.label, label: g.label,
          hint: g.value === null ? ((q.group_hints || {})[g.label] || g.members.map(m => m.label).join(' · ')) : '',
          remaining: rem.length ? (Math.min(...rem) === Math.max(...rem) ? Math.min(...rem) : `${Math.min(...rem)}~${Math.max(...rem)}`) : undefined,
          group: g.value === null ? g.label : null, value: g.value};
      });
    }
    const list = grouped ? ch.filter(c => c.group === S.group || c.value === 'UNKNOWN') : ch;
    return list.map(c => ({key: 'v:' + JSON.stringify(c.value), label: c.label, hint: c.hint, remaining: c.remaining, value: c.value}));
  }
  function groupBody(g) {
    if (g.kind === 'one_of') {
      return `<fieldset class="survey-options sv-options" data-count="${g.options.length}"><legend class="sr-only">답변 선택</legend>
        ${g.options.map((o, i) => `<label class="${S.gsel === i ? 'is-selected' : ''}">
          <input type="radio" name="sv-gopt" data-act="gpick" data-i="${i}" ${S.gsel === i ? 'checked' : ''}>
          <span class="radio-mark"></span><span class="option-index">${String(i + 1).padStart(2, '0')}</span>
          <span class="sv-option-text"><strong>${esc(o.label)}</strong>${o.hint ? `<small>${esc(o.hint)}</small>` : ''}</span></label>`).join('')}
        </fieldset>`;
    }
    if (g.kind === 'each') {
      return `<div class="sv-group-items">${g.all_no ? `<button class="button button-quiet sv-all-no" type="button" data-act="gallno">${esc(g.all_no.label)}</button>` : ''}
        ${g.items.map(it => `<div class="sv-group-item"><p class="sv-group-q"><strong>${esc(it.question)}</strong>
            ${(it.how_to_check || []).length ? `<small>${esc(it.how_to_check[0])}</small>` : ''}</p>
          <div class="sv-seg" role="radiogroup" aria-label="${esc(it.label)}">${it.choices.map((c, j) =>
            `<button type="button" class="${JSON.stringify(S.gvals[it.fact]) === JSON.stringify(c.value) ? 'is-on' : ''}" data-act="gval" data-fact="${esc(it.fact)}" data-j="${j}">${esc(c.label)}</button>`).join('')}</div></div>`).join('')}</div>`;
    }
    // report: 성적서 유무 → 있으면 값을 한꺼번에, 없으면 필요한 시험 목록
    const has = S.greport === 'yes';
    return `<fieldset class="survey-options sv-options" data-count="2"><legend class="sr-only">성적서</legend>
        ${[['yes', g.has_report_label], ['no', g.no_report_label]].map(([k, label], i) => `<label class="${S.greport === k ? 'is-selected' : ''}">
          <input type="radio" name="sv-rep" data-act="greport" data-k="${k}" ${S.greport === k ? 'checked' : ''}>
          <span class="radio-mark"></span><span class="option-index">${String(i + 1).padStart(2, '0')}</span>
          <span class="sv-option-text"><strong>${esc(label)}</strong></span></label>`).join('')}</fieldset>
      ${has ? `<div class="sv-group-items">${g.items.map(it => `<label class="sv-report-row"><span>${esc(it.label)}
          ${(it.thresholds || []).length ? `<small>기준 ${esc(it.thresholds.join(', '))}</small>` : ''}</span>
          <input type="number" step="any" min="0" data-bind="gnum" data-fact="${esc(it.fact)}" value="${esc(S.gnums[it.fact] || '')}" placeholder="비우면 모름">
          <em>${esc(it.unit || '')}</em></label>`).join('')}</div>`
        : S.greport === 'no' ? `<div class="sv-notice"><p>아래 시험을 받아 오면 이어서 판정할 수 있어요.</p><ul class="sv-engine-list">${g.items.map(it =>
          `<li><b>${esc(it.test.item || it.label)}</b>${it.test.method ? ` — ${esc(it.test.method)}` : ''}</li>`).join('')}</ul></div>` : ''}`;
  }
  function groupReady(g) {
    if (g.kind === 'one_of') return S.gsel != null;
    if (g.kind === 'each') return g.items.every(it => it.fact in S.gvals);
    return S.greport === 'no' || (S.greport === 'yes' && g.items.some(it => (S.gnums[it.fact] || '').trim() !== ''));
  }
  function groupAnswers(g) {
    if (g.kind === 'one_of') return g.options[S.gsel].answers;
    if (g.kind === 'each') return {...S.gvals};
    const out = {};
    g.items.forEach(it => { const t = (S.gnums[it.fact] || '').trim();
      out[it.fact] = S.greport === 'yes' && t !== '' && Number.isFinite(Number(t)) ? Number(t) : 'UNKNOWN'; });
    return out;
  }
  function countPanel(r, q, sel) {
    const v = S.view;
    const count = r.candidates ? r.candidates.count : null;
    const rawTrail = v.candidate_trail || [];
    const trail = rawTrail.filter((n, i) => i === 0 || n !== rawTrail[i - 1]);
    const prev = rawTrail.length > 1 ? rawTrail[rawTrail.length - 2] : null;
    const initial = trail.length ? trail[0] : count;
    const purpose = q.purpose || r.stage_title || '분류 조건 확인';
    let why;
    if (q.group) why = `${q.group.facts.length}가지를 한 화면에서 확인해요. ${purpose}에 필요합니다.`;
    else if (sel && sel.remaining === 0) why = '이 답이면 분류번호를 정하는 대상에서 빠져요(폐기물 아님·다른 법 적용 등).';
    else if (sel && sel.remaining === count) why = `이 답으로 후보 수는 그대로예요. ${purpose}에 쓰는 답이에요.`;
    else if (sel && typeof sel.remaining === 'number') why = `${count}개 후보를 ${sel.remaining}개로 줄이는 답이에요.`;
    else {
      const rems = (q.choices || []).map(c => c.remaining).filter(x => typeof x === 'number' && x > 0);
      why = rems.length && Math.min(...rems) < count ? `답에 따라 후보가 최소 ${Math.min(...rems)}개까지 줄어요.`
        : `후보 수를 바로 줄이지는 않지만 ${purpose}에 꼭 필요한 질문이에요.`;
    }
    const note = sel && sel.remaining > 0 && count - sel.remaining > 0 ? `이 답 하나로 ${count - sel.remaining}개 후보가 제외돼요` : '';
    const pop = count !== S.lastCount; S.lastCount = count;  // 숫자가 바뀔 때만 강조 애니메이션
    return `<aside class="sv-panel" data-layer-name="CandidatePanel">
        <p class="sv-panel-label">남은 분류번호 후보 · ${esc(purpose)}</p>
        <div class="sv-count"><strong class="${pop ? '' : 'no-pop'}">${count == null ? '-' : count}</strong><span>개</span>
          ${prev != null && prev - count > 0 ? `<em>−${prev - count}개 제외</em>` : ''}</div>
        <div class="sv-bar" aria-hidden="true"><span style="width:${initial ? Math.min(100, count / initial * 100) : 0}%"></span></div>
        <ol class="sv-trail" aria-label="후보 수 변화">${trail.map((n, i) => `<li class="${i === trail.length - 1 ? 'is-current' : ''}">${n}</li>`).join('')}</ol>
        <p class="sv-why">${esc(why)}</p>${note ? `<p class="sv-note">${esc(note)}</p>` : ''}
        ${answeredList()}
      </aside>`;
  }
  function groupView(r, q) {
    const g = q.group, answeredN = (S.view.answered || []).length;
    const ready = groupReady(g);
    return `<main class="sv-shell"><section class="sv-main" aria-labelledby="sv-question">
        <p class="sv-context">새 폐기물 문진 · ${esc(r.stage_title || '')}</p>
        <span class="sv-step">질문 ${(S.view.candidate_trail || []).length || 1}</span>
        <h1 id="sv-question">${esc(g.title)}</h1>
        ${g.help ? `<p class="sv-helper">${esc(g.help)}</p>` : ''}
        ${groupBody(g)}${errLine()}
        <footer class="survey-actions"><button class="button button-quiet" type="button" data-act="back" ${S.view.can_undo ? '' : 'disabled'}>이전</button>
          ${ready ? `<button class="button button-primary" type="button" data-act="gnext">다음 ${arrow}</button>`
                  : '<span class="survey-guide">모든 항목을 고르면 다음으로 넘어갈 수 있어요.</span>'}</footer></section>
      ${countPanel(r, q, null)}</main>`;
  }
  function questionView() {
    const v = S.view, r = v.result, q = r.next_question;
    if (q.group) return groupView(r, q);
    const opts = q.choices ? optionsFor(q) : null;
    const sel = opts && opts.find(o => o.key === S.sel);
    const count = r.candidates ? r.candidates.count : null;
    const answeredN = (v.answered || []).length;
    const test = q.test ? `<p class="sv-helper"><b>시험이 필요해요:</b> ${esc(q.test.item)} — ${esc(q.test.method)}</p>` : '';
    const optionHtml = opts ? `<fieldset class="survey-options sv-options" data-count="${opts.length}"><legend class="sr-only">답변 선택</legend>
      ${opts.map((o, i) => `<label class="${S.sel === o.key ? 'is-selected' : ''}">
        <input type="radio" name="sv-opt" data-act="pick" data-key="${esc(o.key)}" ${S.sel === o.key ? 'checked' : ''}>
        <span class="radio-mark"></span><span class="option-index">${String(i + 1).padStart(2, '0')}</span>
        <span class="sv-option-text"><strong>${esc(o.label)}</strong>${o.hint ? `<small>${esc(o.hint)}</small>` : ''}
          ${o.remaining !== undefined ? `<small class="sv-engine-remaining">${o.remaining === 0 ? '분류 대상에서 빠짐' : o.remaining === count ? `후보 ${esc(o.remaining)}개 그대로` : `→ 후보 ${esc(o.remaining)}개`}</small>` : ''}</span></label>`).join('')}
      </fieldset>`
      : `<div class="sv-engine-number"><input type="number" step="any" data-bind="num" value="${esc(S.num)}" aria-label="값 입력">
         <span>${esc(q.unit || '')}</span>
         <button class="button button-quiet" type="button" data-act="unknown">모름</button></div>`;
    const ready = opts ? !!sel : S.num !== '' && !isNaN(parseFloat(S.num));
    const canBack = S.group != null || v.can_undo;
    return `<main class="sv-shell"><section class="sv-main" aria-labelledby="sv-question">
        <p class="sv-context">새 폐기물 문진 · ${esc(r.stage_title || '')}</p>
        <span class="sv-step">질문 ${(S.view.candidate_trail || []).length || 1}</span>
        <h1 id="sv-question">${esc(S.group != null ? `${q.question} — ${S.group}` : q.question)}</h1>
        ${q.why ? `<p class="sv-helper">${esc(q.why)}</p>` : ''}
        ${(q.how_to_check || []).length ? `<details class="sv-question-help"><summary>어디서 확인하나요?</summary><ul>${q.how_to_check.map(h => `<li>${esc(h)}</li>`).join('')}</ul>${q.note ? `<p>${esc(q.note)}</p>` : ''}</details>` : ''}
        ${test}${lawBlock(q)}${optionHtml}${errLine()}
        <footer class="survey-actions">${questionActions(canBack, ready)}</footer></section>
      ${countPanel(r, q, sel)}</main>`;
  }
  function evidence(trail) {
    return `<section aria-labelledby="sv-evidence"><h2 id="sv-evidence" class="sv-h2">판정 근거</h2>
      <div class="sv-evidence">${trail.map((t, i) => `<article>
        <span class="sv-evidence-num">${String(i + 1).padStart(2, '0')}</span>
        <h3>${esc(t.title)}</h3><p>${esc((t.basis[0] || {}).cite || '')}</p><strong>${esc(t.outcome)}</strong>
        <button type="button" data-act="law-t" data-i="${i}">근거 조문 보기 ${arrow}</button></article>`).join('')}</div></section>`;
  }
  function recycling(s5) {
    if (!s5) return '';
    const g = s5.recycling_groups;
    if (!g) return `<section aria-labelledby="sv-recycle"><h2 id="sv-recycle" class="sv-h2">재활용</h2>
      <div class="sv-notice"><p><b>${esc(s5.label)}</b><br>${esc(s5.why || '')}</p></div></section>`;
    const block = (key, cls, title, sub) => g[key] ? `<div class="sv-group ${cls}"><header>
        <span class="lime-status"></span><div><strong>${title}</strong><small>${sub}</small></div><em>${g[key].length}개</em></header>
        <ul>${g[key].map(a => `<li><b>${esc(a.r_code)}</b><span>${esc(a.definition || '')}</span></li>`).join('')}</ul></div>` : '';
    return `<section aria-labelledby="sv-recycle"><h2 id="sv-recycle" class="sv-h2">허용 재활용 유형</h2>
      <div class="sv-agent" data-mode="lookup"><span class="sv-agent-lookup">▤</span><p>시행규칙 별표 4의3에서 조회한 결과입니다</p></div>
      <div class="sv-groups">${block('no_pre_analysis', 'is-free', '사전 분석·확인 해당 없음', '이 표에서는 사전 분석 대상으로 표시되지 않았어요')}
        ${block('pre_analysis', 'is-analysis', '사전 분석·확인 해당', '분석 결과가 먼저 필요해요')}
        ${block('unmarked', 'is-analysis', '표에 표기 없음', '원문 칸이 비어 있어요')}</div>
      <div class="sv-notice"><p><b>${esc(s5.label)}</b><br>${esc(s5.why || '')}</p></div></section>`;
  }
  function resultView() {
    const r = S.view.result;
    const dec = r.decided || [];
    const s2 = dec.find(d => d.stage === 'S2'), s3 = dec.find(d => d.stage === 'S3');
    const s4 = dec.find(d => d.stage === 'S4'), s5 = dec.find(d => d.stage === 'S5');
    const trail = r.trail || [];
    const actions = `<footer class="sv-result-actions">
      <button class="button button-quiet" type="button" data-act="restart">다시 문진하기</button>
      ${S.view.can_undo ? '<button class="button button-quiet" type="button" data-act="back">마지막 답 고치기</button>' : ''}
      <button class="button button-primary" type="button" data-act="exit">저장한 문진 나가기 ${arrow}</button></footer>`;
    const provisional = r.provisional ? `<div class="sv-notice sv-engine-warn"><p><b>잠정 결과예요.</b> ${esc(r.message || '')}
      처리 전에 관할 기관이나 전문가 확인을 권합니다.</p></div>` : '';
    if (s4) {
      const [code, ...name] = s4.label.split(' ');
      return `<main class="sv-result"><header class="sv-result-head">
          <div class="sv-badges">${s3 ? `<span>${esc(s3.label)}</span>` : ''}${s2 ? `<span>${esc(s2.label)}</span>` : ''}</div>
          <p class="sv-result-label">분류번호</p><h1>${esc(code)}</h1><p class="sv-result-name">${esc(name.join(' '))}</p>
          <div class="sv-agent" data-mode="lookup"><span class="sv-agent-lookup">▤</span>
            <p>${s4.user_selected ? '명칭을 보고 직접 선택한 번호입니다. 엔진은 앞 단계와의 일치를 확인했습니다.' : '법령 기준표에서 범위를 좁혀 번호를 정했습니다.'} · 판정 기준일 ${esc(r.as_of)}</p></div></header>
        ${provisional}${checksView(r)}${resolveView(r)}${reportingView(r)}${answeredList()}${evidence(trail)}${recycling(s5)}<p class="sv-helper">재활용 유형은 법령 표의 조회 결과입니다. 실제 처리 경로와 업체는 별도 확인이 필요해요.</p>${errLine()}${actions}</main>`;
    }
    // 분류번호까지 가지 못함: 결론(폐기물 아님 등) 또는 확인·시험·문의 안내
    const last = dec[dec.length - 1];
    const title = r.status === 'DETERMINED' && last ? last.label : '확인이 필요해요';
    const consult = r.consult ? `<div class="sv-notice"><p><b>법 조문만으로 정할 수 없어 결론을 내지 않았어요.</b><br>${esc(r.consult.why)}</p></div>
      ${r.reference_conclusion ? `<p class="sv-helper">참고: ${esc(r.reference_conclusion)}</p>` : ''}
      <h2 class="sv-h2">문의처</h2><ul class="sv-engine-list">${r.consult.where.map(w => `<li>${esc(w)}</li>`).join('')}</ul>
      <details class="sv-engine-draft"><summary>질의서 초안</summary><pre>${esc(r.consult.draft)}</pre></details>` : '';
    const resolve = (r.how_to_resolve || []).length ? `<h2 class="sv-h2">확인할 것</h2><ul class="sv-engine-list">${r.how_to_resolve.map(h =>
      `<li><b>${esc(h.question)}</b><br>${esc((h.how_to_check || []).join(' / '))}${h.test ? `<br>시험: ${esc(h.test.item)} — ${esc(h.test.method)}` : ''}</li>`).join('')}</ul>` : '';
    return `<main class="sv-result"><header class="sv-result-head">
        <div class="sv-badges">${dec.map(d => `<span>${esc(d.label)}</span>`).join('')}</div>
        <p class="sv-result-label">${esc(r.stage_title || '판정 결과')}</p><h1 class="sv-engine-h1">${esc(title)}</h1>
        ${last && last.why ? `<p class="sv-result-name">${esc(last.why)}</p>` : ''}
        ${r.message && !r.consult ? `<p class="sv-helper">${esc(r.message)}</p>` : ''}</header>
      ${provisional}${consult}${checksView(r)}${resolve}${reportingView(r)}${answeredList()}${trail.length ? evidence(trail) : ''}${errLine()}${actions}</main>`;
  }

  function overlay() {
    if (S.edit) {
      const q = S.edit;
      return `<div class="overlay-backdrop" role="presentation"><section class="analysis-panel detail-overlay" role="dialog" aria-modal="true" aria-labelledby="sv-edit-title">
        <header class="panel-header"><h2 id="sv-edit-title">${esc(q.question)}</h2><button class="icon-button" type="button" data-act="cancel-edit" aria-label="닫기">✕</button></header>
        <div class="legal-content"><p class="sv-helper">앞 답이 바뀌면 영향을 받는 뒤 답만 다시 확인해요.</p>
          ${q.choices ? `<label for="sv-edit-value">답변</label><select id="sv-edit-value" class="sv-edit-value" data-bind="edit-value"><option value="-1">선택해 주세요</option>${q.choices.map((o, i) => `<option value="${i}" ${q.input === String(i) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`
            : `<label for="sv-edit-value">값 ${esc(q.unit || '')}</label><input id="sv-edit-value" class="sv-edit-value" type="number" step="any" min="0" data-bind="edit-value" value="${esc(q.input)}">`}
          ${errLine()}<footer class="survey-actions"><button class="button button-quiet" type="button" data-act="cancel-edit">취소</button>${!q.choices ? '<button class="button button-quiet" type="button" data-act="edit-unknown">모름</button>' : ''}<button class="button button-primary" type="button" data-act="submit-edit">확인하고 이어가기</button></footer>
        </div></section></div>`;
    }
    if (!S.overlay) return '';
    const o = S.overlay;
    return `<div class="overlay-backdrop" role="presentation" data-act="close-bg">
      <section class="analysis-panel detail-overlay" role="dialog" aria-modal="true" aria-labelledby="sv-law-title" data-layer-name="L4-LawArticle">
        <header class="panel-header"><div><span class="panel-kicker">${esc(o.kicker)}</span><h2 id="sv-law-title">근거 조문</h2></div>
          <button class="icon-button" type="button" data-act="close" aria-label="닫기">✕</button></header>
        <div class="legal-content">
          ${o.basis.map(b => `<span>조문 · ${esc(b.cite)}${b.evidence && b.evidence !== 'LAW' ? ' (법령 아님)' : ''}</span>
            <blockquote>“${esc(b.quote)}”</blockquote>`).join('')}
          <h3>${esc(o.title)}</h3>
          ${o.reasons.length ? `<div class="law-reasons"><strong>이 폐기물에 해당하는 이유</strong>
            ${o.reasons.map((x, i) => `<p><span>${String(i + 1).padStart(2, '0')}</span> ${esc(x)}</p>`).join('')}</div>` : ''}
          <a class="law-source-link" href="https://www.law.go.kr/" target="_blank" rel="noreferrer">원문 보기 ${arrow}</a>
          <small>${esc(o.version || '')}${o.version ? ' · ' : ''}판정 기준일 ${esc(S.view ? S.view.result.as_of : S.asOf)}</small>
        </div></section></div>`;
  }

  function render() {
    let body = '';
    if (S.phase === 'intake' || S.phase === 'reading') body = intake();
    else if (S.phase === 'confirm') body = confirmView();
    else if (S.phase === 'question') body = questionView();
    else body = resultView();
    const variant = S.phase === 'question' ? (S.sel ? 'answered' : 'unanswered') : S.phase;
    root.innerHTML = `<div class="l3-page sv-page" data-layer-name="${S.phase === 'result' ? 'L3-SurveyResult' : 'L3-Survey'}" data-variant="${variant}">
      ${workbar()}${progress()}${body}${berryDock()}${overlay()}</div>`;
    if (S.saving || S.loading) root.querySelectorAll('button, input, select, textarea').forEach(el => { el.disabled = true; });
  }

  // ---------------------------------------------------------------- 동작
  root.addEventListener('input', e => {
    const b = e.target.dataset.bind;
    if (b === 'text') { S.text = e.target.value; const btn = root.querySelector('[data-act=extract]');
      if (btn) btn.disabled = !S.text.trim() || !S.llm; }
    if (b === 'num') { S.num = e.target.value; const ok = S.num !== '' && !isNaN(parseFloat(S.num));
      const f = root.querySelector('.survey-actions');
      if (f && ok !== !!root.querySelector('[data-act=next]')) f.innerHTML = questionActions(S.group != null || S.view.can_undo, ok); }
    if (b === 'edit-value' && S.edit) S.edit.input = e.target.value;
    if (b === 'gnum') { S.gnums[e.target.dataset.fact] = e.target.value;
      const g = S.view.result.next_question.group, f = root.querySelector('.survey-actions');
      if (f && groupReady(g) !== !!root.querySelector('[data-act=gnext]')) {
        const btn = groupReady(g) ? `<button class="button button-primary" type="button" data-act="gnext">다음 ${arrow}</button>`
          : '<span class="survey-guide">모든 항목을 고르면 다음으로 넘어갈 수 있어요.</span>';
        f.lastElementChild.outerHTML = btn; } }
  });
  root.addEventListener('click', e => {
    const el = e.target.closest('[data-act]');
    if (!el) return;
    if (S.saving || S.loading) return;
    const act = el.dataset.act;
    if (act === 'close-bg' && e.target !== el) return;
    const r = S.view && S.view.result;
    switch (act) {
      case 'exit': location.hash = '#/wastes'; break;
      case 'edit-fact': run(() => editFact(el.dataset.fact)); break;
      case 'edit-unknown': run(() => sendAnswer(S.edit.fact, 'UNKNOWN')); break;
      case 'law-report': { const item = r.reporting[el.dataset.key];
        S.overlay = {kicker: '신고·처리계획 확인', title: item.label,
          basis: item.basis.map(b => ({...b, cite: b.title + ' ' + b.location})), reasons: [item.why],
          version: [...new Set(item.basis.map(b => b.law_version))].join(', ')}; render(); break; }
      case 'cancel-edit': S.edit = null; S.err = ''; render(); break;
      case 'submit-edit': run(async () => {
        const q = S.edit;
        const value = q.choices ? (q.choices[Number(q.input)] || {}).value : q.input.trim() !== '' ? Number(q.input) : undefined;
        if (value === undefined || (typeof value === 'number' && (!Number.isFinite(value) || value < 0))) throw new Error('답변을 선택하거나 올바른 값을 입력해 주세요.');
        await sendAnswer(q.fact, value);
      }); break;
      case 'example': S.text = [
        '사출 공장 3번 라인에서 나오는 성형 불량품과 스프루, 런너를 월 2.3톤 정도 버려요',
        '프레스 공장인데 절삭유 묻은 철 칩이 나와요. 대기 배출시설 신고는 돼 있어요.'][+el.dataset.i]; render(); break;
      case 'plain': run(() => startSession({})); break;
      case 'extract': run(async () => {
        S.phase = 'reading'; say('입력하신 내용을 읽고 있어요');
        try {
          const j = await api('/api/extract', {text: S.text});
          S.proposed = j.proposed.map(p => ({...p, keep: true}));
          if (!S.proposed.length) { S.phase = 'intake'; say('확실히 읽힌 사실이 없어요. 질문으로 바로 시작해 주세요', 3000); return; }
          S.phase = 'confirm'; say('이렇게 읽었어요. 맞는지 확인해 주세요');
        } catch (err) { S.phase = 'intake'; throw err; }
      }); break;
      case 'cue': S.proposed[+el.dataset.i].keep = el.checked; break;
      case 'edit': S.phase = 'intake'; say('어떤 폐기물인지 편하게 적어 주세요'); break;
      case 'confirm': run(() => {
        const answers = {}; S.proposed.filter(p => p.keep).forEach(p => { answers[p.fact] = p.value; });
        return startSession(answers);
      }); break;
      case 'pick': S.sel = el.dataset.key; render(); break;
      case 'gpick': S.gsel = +el.dataset.i; render(); break;
      case 'gval': { const it = r.next_question.group.items.find(x => x.fact === el.dataset.fact);
        S.gvals[it.fact] = it.choices[+el.dataset.j].value; render(); break; }
      case 'gallno': S.gvals = {...r.next_question.group.all_no.answers}; render(); break;
      case 'greport': S.greport = el.dataset.k; render(); break;
      case 'gnext': { const g = r.next_question.group; if (groupReady(g)) run(() => sendAnswers(groupAnswers(g))); break; }
      case 'unknown': run(() => sendAnswer(r.next_question.fact, 'UNKNOWN')); break;
      case 'next': {
        const q = r.next_question;
        if (!q.choices) { run(() => sendAnswer(q.fact, parseFloat(S.num))); break; }
        const o = optionsFor(q).find(x => x.key === S.sel);
        if (!o) break;
        if (o.group) { S.group = o.group; S.sel = null; render(); break; }  // 묶음 → 그 안의 보기
        run(() => sendAnswer(q.fact, o.value)); break;
      }
      case 'back':
        if (S.group != null) { S.group = null; S.sel = null; render(); }
        else run(undo);
        break;
      case 'restart': S.view = null; S.phase = 'intake'; S.proposed = []; S.edit = null; S.err = ''; S.saveFailed = false;
        try { localStorage.removeItem(storageKey); } catch (_) {} say('어떤 폐기물인지 편하게 적어 주세요'); break;
      case 'law-q': { const q = r.next_question;
        S.overlay = {kicker: r.stage_title, title: q.question, basis: q.law, reasons: q.why ? [q.why] : [], version: ''}; render(); break; }
      case 'law-t': { const t = r.trail[+el.dataset.i];
        S.overlay = {kicker: `${t.title} · ${t.outcome}`, title: t.outcome, basis: t.basis,
          reasons: [...t.answers.map(a => `${a.label}: ${a.value_text}`), ...(t.because || []), ...(t.plain ? [t.plain] : [])],
          version: t.basis.map(b => b.law_version).filter(Boolean).join(', ')};
        render(); break; }
      case 'close': case 'close-bg': S.overlay = null; render(); break;
    }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !S.saving && (S.overlay || S.edit)) { S.overlay = null; S.edit = null; render(); } });

  async function initialize() {
    try {
      const s = await api('/api/status'); S.llm = !!(s.llm && s.llm.enabled); S.asOf = s.as_of; S.siteFacts = s.site_facts || [];
      let sid = null;
      try { sid = localStorage.getItem(storageKey); } catch (_) {}
      if (sid) {
        S.view = await api('/api/session/' + encodeURIComponent(sid));
        afterView('저장한 답변을 불러왔어요');
      }
    } catch (e) { S.err = String(e.message || e); }
    finally { S.loading = false; render(); }
  }
  initialize();
  render();
})();
