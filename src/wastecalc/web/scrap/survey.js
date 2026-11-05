/* SCRAP 문진 화면 — 엔진 연결판.
 * SCRAP.html(Figma Make 내보내기)의 문진 경로(#/wastes/<id>/survey)에서만 동작한다.
 * 화면 구조·클래스 이름은 디자인의 문진 화면(L3-Survey)을 따르고, 질문·보기·후보 수·근거·재활용 유형은
 * 모두 엔진 API(/api/session …)의 결과를 그대로 보여 준다. 판정은 화면에서 하지 않는다.
 */
(function () {
  if (!window.__ENGINE_SURVEY) return;
  const root = document.getElementById('root');
  const wasteId = (window.__route().path.split('/')[2]) || 'new';
  const STAGE_INDEX = {S0: 0, S1: 1, S2: 2, S3: 3, S4: 4, S5: 5};
  const S = {
    phase: 'intake', text: '', proposed: [], view: null, sel: null, num: '', group: null,
    overlay: null, berry: '어떤 폐기물인지 편하게 적어 주세요', saving: false, llm: false, asOf: '', judgeStep: 0, err: '',
  };

  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const arrow = '<span aria-hidden="true">→</span>';

  async function api(path, body) {
    const r = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'Content-Type': 'application/json'},
      body: body ? JSON.stringify(body) : undefined});
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
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
  async function startSession(answers) {
    S.view = await api('/api/session', {answers, strict: true});
    S.sel = null; S.group = null; S.num = '';
    afterView('질문으로 후보를 좁혀 볼게요');
  }
  async function sendAnswer(fact, value) {
    S.saving = true; render();
    S.view = await api(`/api/session/${S.view.session_id}/answer`, {fact, value});
    S.saving = false; S.sel = null; S.group = null; S.num = '';
    afterView('답변이 앞선 내용과 맞는지 살펴보고 있어요');
  }
  async function undo() {
    S.view = await api(`/api/session/${S.view.session_id}/undo`, {});
    S.sel = null; S.group = null; S.num = ''; S.phase = 'question'; render();
  }
  function afterView(msg) {
    const r = S.view.result;
    if (r.next_question) { S.phase = 'question'; say(msg, 1600); return; }
    S.phase = 'judging'; S.judgeStep = 0; render(); judge();
  }
  const JUDGE = [['ai', '답변을 모아서 읽고 있어요'], ['ai', '답변이 서로 맞는지 살펴보고 있어요'],
    ['system', '법조문을 조회하고 있습니다'], ['system', '분류번호를 판정하고 있습니다'], ['system', '허용 재활용 유형을 조회하고 있습니다']];
  function judge() {
    if (S.phase !== 'judging') return;
    if (S.judgeStep >= JUDGE.length) { S.phase = 'result'; S.berry = null; render(); return; }
    setTimeout(() => { S.judgeStep += 1; render(); judge(); }, 350);
  }

  // ---------------------------------------------------------------- 화면 조각
  function workbar() {
    const r = S.view && S.view.result;
    const s4 = r && (r.decided || []).find(d => d.stage === 'S4');
    const name = s4 ? s4.label : '새 폐기물 문진';
    return `<header class="l3-workbar" data-layer-name="L3-WorkBar">
      <button type="button" data-act="exit"><span>←</span>나가기</button>
      <strong>${esc(name)}</strong>
      <span class="${S.saving ? 'is-saving' : ''}">${S.saving ? '저장 중...' : '자동 저장됨'}</span></header>`;
  }
  function progress() {
    let w = 0;
    if (S.phase === 'question' && S.view) w = ((STAGE_INDEX[S.view.result.stage] || 0) + 0.5) / 6 * 100;
    if (S.phase === 'judging' || S.phase === 'result') w = 100;
    return `<div class="survey-progress-track"><span style="width:${w}%"></span></div>`;
  }
  function berryDock() {
    return `<div class="berry-dock" data-speaking="${S.berry ? 'true' : 'false'}" data-layer-name="Agent-Berry">
      <img src="/scrap-engine/berry.png" alt="에이전트 베리">
      ${S.berry ? `<p class="berry-bubble" role="status"><b>베리</b>${esc(S.berry)}</p>` : ''}</div>`;
  }
  function errLine() { return S.err ? `<p class="sv-engine-err" role="alert">${esc(S.err)}</p>` : ''; }

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
      ${S.llm ? '' : '<p class="sv-helper sv-engine-note">LLM이 연결되지 않아 설명 읽기는 쓸 수 없어요(.env 설정). 질문으로 바로 시작하세요.</p>'}
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
        return {key: 'g:' + g.label, label: g.label, hint: g.value === null ? g.members.map(m => m.label).join(' · ') : '',
          remaining: rem.length ? (Math.min(...rem) === Math.max(...rem) ? Math.min(...rem) : `${Math.min(...rem)}~${Math.max(...rem)}`) : undefined,
          group: g.value === null ? g.label : null, value: g.value};
      });
    }
    const list = grouped ? ch.filter(c => c.group === S.group || c.value === 'UNKNOWN') : ch;
    return list.map(c => ({key: 'v:' + JSON.stringify(c.value), label: c.label, hint: c.hint, remaining: c.remaining, value: c.value}));
  }
  function questionView() {
    const v = S.view, r = v.result, q = r.next_question;
    const opts = q.choices ? optionsFor(q) : null;
    const sel = opts && opts.find(o => o.key === S.sel);
    const count = r.candidates ? r.candidates.count : null;
    const trail = v.candidate_trail || [];
    const prev = trail.length > 1 ? trail[trail.length - 2] : null;
    const initial = trail.length ? trail[0] : count;
    const rems = (q.choices || []).map(c => c.remaining).filter(x => typeof x === 'number');
    let why = '';
    if (sel && typeof sel.remaining === 'number') why = `${count}개 후보를 ${sel.remaining}개로 줄이는 답이에요.`;
    else if (rems.length && Math.min(...rems) < count) why = `답에 따라 ${count}개 후보가 최소 ${Math.min(...rems)}개까지 줄어요.`;
    else if (count != null) why = '이 질문은 분류번호 후보 수를 바로 줄이지는 않지만, 법적 구분에 필요해요.';
    const note = sel && typeof sel.remaining === 'number' && count - sel.remaining > 0 ? `이 답 하나로 ${count - sel.remaining}개 후보가 제외돼요` : '';
    const answeredN = (v.answered || []).length;
    const test = q.test ? `<p class="sv-helper"><b>시험이 필요해요:</b> ${esc(q.test.item)} — ${esc(q.test.method)}</p>` : '';
    const optionHtml = opts ? `<fieldset class="survey-options sv-options" data-count="${opts.length}"><legend class="sr-only">답변 선택</legend>
      ${opts.map((o, i) => `<label class="${S.sel === o.key ? 'is-selected' : ''}">
        <input type="radio" name="sv-opt" data-act="pick" data-key="${esc(o.key)}" ${S.sel === o.key ? 'checked' : ''}>
        <span class="radio-mark"></span><span class="option-index">${String(i + 1).padStart(2, '0')}</span>
        <span class="sv-option-text"><strong>${esc(o.label)}</strong>${o.hint ? `<small>${esc(o.hint)}</small>` : ''}
          ${o.remaining !== undefined ? `<small class="sv-engine-remaining">→ 후보 ${esc(o.remaining)}개</small>` : ''}</span></label>`).join('')}
      </fieldset>`
      : `<div class="sv-engine-number"><input type="number" step="any" data-bind="num" value="${esc(S.num)}" aria-label="값 입력">
         <span>${esc(q.unit || '')}</span>
         <button class="button button-quiet" type="button" data-act="unknown">모름</button></div>`;
    const ready = opts ? !!sel : S.num !== '' && !isNaN(parseFloat(S.num));
    const canBack = S.group != null || v.can_undo;
    return `<main class="sv-shell"><section class="sv-main" aria-labelledby="sv-question">
        <p class="sv-context">새 폐기물 문진 · ${esc(r.stage_title || '')}</p>
        <span class="sv-step">질문 ${answeredN + 1}</span>
        <h1 id="sv-question">${esc(S.group != null ? `${q.question} — ${S.group}` : q.question)}</h1>
        ${q.why ? `<p class="sv-helper">${esc(q.why)}</p>` : ''}
        ${test}${lawBlock(q)}${optionHtml}${errLine()}
        <footer class="survey-actions">
          <button class="button button-quiet" type="button" data-act="back" ${canBack ? '' : 'disabled'}>이전</button>
          ${ready ? `<button class="button button-primary" type="button" data-act="next">다음 ${arrow}</button>`
                  : '<span class="survey-guide">답변을 선택하면 다음 단계로 이동할 수 있어요.</span>'}
        </footer></section>
      <aside class="sv-panel" data-layer-name="CandidatePanel">
        <p class="sv-panel-label">남은 분류번호 후보</p>
        <div class="sv-count"><strong>${count == null ? '-' : count}</strong><span>개</span>
          ${prev != null && prev - count > 0 ? `<em>−${prev - count}개 제외</em>` : ''}</div>
        <div class="sv-bar" aria-hidden="true"><span style="width:${initial ? count / initial * 100 : 0}%"></span></div>
        <ol class="sv-trail" aria-label="후보 수 변화">${trail.map((n, i) => `<li class="${i === trail.length - 1 ? 'is-current' : ''}">${n}</li>`).join('')}</ol>
        <p class="sv-why">${esc(why)}</p>${note ? `<p class="sv-note">${esc(note)}</p>` : ''}
        ${(v.answered || []).length ? `<details class="sv-engine-answered"><summary>입력한 답 ${answeredN}개</summary><ul>${v.answered.map(a =>
          `<li>${esc(a.label)}: <b>${esc(a.value_text)}</b></li>`).join('')}</ul></details>` : ''}
      </aside></main>`;
  }
  function judgingView() {
    const cur = JUDGE[Math.min(S.judgeStep, JUDGE.length - 1)];
    return `<main class="sv-judging" data-layer-name="Survey-Waiting"><div class="sv-wait">
      <div class="sv-wait-head"><span class="sv-wait-sys">⌛</span><h1>${esc(cur[0] === 'system' ? cur[1] : '입력 내용을 검토하고 있습니다')}</h1></div>
      <ol class="sv-wait-list" aria-label="진행 상황">${JUDGE.map((j, i) => `<li class="${i < S.judgeStep ? 'is-done' : i === S.judgeStep ? 'is-active' : ''}">
        <span class="sv-wait-dot">${i < S.judgeStep ? '✓' : ''}</span><span>${esc(j[1])}</span></li>`).join('')}</ol></div></main>`;
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
      <div class="sv-groups">${block('no_pre_analysis', 'is-free', '사전 분석·확인 해당 없음', '바로 진행할 수 있어요')}
        ${block('pre_analysis', 'is-analysis', '사전 분석·확인 해당', '분석 결과가 먼저 필요해요')}
        ${block('unmarked', 'is-analysis', '표에 표기 없음', '원문 칸이 비어 있어요')}</div>
      <div class="sv-notice"><p>${esc(s5.why || '')}</p></div></section>`;
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
      ${s4 ? `<a class="button button-primary" href="/wastes/${esc(wasteId)}/match">저장하고 처리 경로 선택 ${arrow}</a>` : ''}</footer>`;
    const provisional = r.provisional ? `<div class="sv-notice sv-engine-warn"><p><b>잠정 결과예요.</b> ${esc(r.message || '')}
      처리 전에 관할 기관이나 전문가 확인을 권합니다.</p></div>` : '';
    if (s4) {
      const [code, ...name] = s4.label.split(' ');
      return `<main class="sv-result"><header class="sv-result-head">
          <div class="sv-badges">${s3 ? `<span>${esc(s3.label)}</span>` : ''}${s2 ? `<span>${esc(s2.label)}</span>` : ''}</div>
          <p class="sv-result-label">분류번호</p><h1>${esc(code)}</h1><p class="sv-result-name">${esc(name.join(' '))}</p>
          <div class="sv-agent" data-mode="lookup"><span class="sv-agent-lookup">▤</span>
            <p>분류번호는 법령 기준표에서 조회한 결과입니다 · 판정 기준일 ${esc(r.as_of)}</p></div></header>
        ${provisional}${evidence(trail)}${recycling(s5)}${errLine()}${actions}</main>`;
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
      ${provisional}${consult}${resolve}${trail.length ? evidence(trail) : ''}${errLine()}${actions}</main>`;
  }

  function overlay() {
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
    else if (S.phase === 'judging') body = judgingView();
    else body = resultView();
    const variant = S.phase === 'question' ? (S.sel ? 'answered' : 'unanswered') : S.phase;
    root.innerHTML = `<div class="l3-page sv-page" data-layer-name="${S.phase === 'result' ? 'L3-SurveyResult' : 'L3-Survey'}" data-variant="${variant}">
      ${workbar()}${progress()}${body}${berryDock()}${overlay()}</div>`;
  }

  // ---------------------------------------------------------------- 동작
  root.addEventListener('input', e => {
    const b = e.target.dataset.bind;
    if (b === 'text') { S.text = e.target.value; const btn = root.querySelector('[data-act=extract]');
      if (btn) btn.disabled = !S.text.trim() || !S.llm; }
    if (b === 'num') { S.num = e.target.value; const ok = S.num !== '' && !isNaN(parseFloat(S.num));
      const f = root.querySelector('.survey-actions'); if (f && ok !== !!root.querySelector('[data-act=next]')) render(); }
  });
  root.addEventListener('click', e => {
    const el = e.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act;
    if (act === 'close-bg' && e.target !== el) return;
    const r = S.view && S.view.result;
    switch (act) {
      case 'exit': location.hash = '#/wastes'; break;
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
      case 'restart': S.view = null; S.phase = 'intake'; S.proposed = []; say('어떤 폐기물인지 편하게 적어 주세요'); break;
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
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && S.overlay) { S.overlay = null; render(); } });

  api('/api/status').then(s => { S.llm = !!(s.llm && s.llm.enabled); S.asOf = s.as_of; render(); })
    .catch(e => { S.err = String(e.message || e); render(); });
  render();
})();
