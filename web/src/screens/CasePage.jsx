import { useEffect, useRef, useState } from 'react';
import { api } from '../api/index.js';
import { STATUS_LABEL } from '../lib/labels.js';
import { useLoad } from '../lib/useLoad.js';
import { navigate } from '../lib/router.js';
import QuestionCard from '../components/QuestionCard.jsx';
import Board from '../components/Board.jsx';
import { ConflictCard, EvidenceCard, FinalCard, UnsupportedCard } from '../components/BranchCards.jsx';

export default function CasePage({ id }) {
  const { data, error, loading, reload } = useLoad(() => api.getCase(id), [id]);
  const [conv, setConv] = useState([]);
  const [turn, setTurn] = useState(null);
  const [kase, setKase] = useState(null);
  const [handoff, setHandoff] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [retry, setRetry] = useState(null);
  const [upload, setUpload] = useState(false);
  const [hint, setHint] = useState('');
  const [text, setText] = useState('');
  const composer = useRef(null);

  useEffect(() => {
    if (!data) return;
    setConv(data.conversation);
    setTurn(data.latest_turn);
    setKase(data.case);
    setHandoff(data.handoff);
  }, [data]);

  if (error) return <p className="wd-alert" role="alert">{error.message} <a href="#/cases">목록으로</a></p>;
  if (loading && !turn) return <p className="muted">불러오는 중…</p>;
  if (!turn || !kase) return null;

  const confirmed = kase.status === 'CODE_CONFIRMED' || kase.status === 'IN_TRANSIT' || kase.status === 'COMPLETED';

  /** 서버 호출 공통: 잠금, 오류 처리(409 stale → 새로 불러오기, 네트워크 → 다시 보내기) */
  async function run(userText, call, again) {
    setBusy(true);
    setErr(null);
    setRetry(null);
    setConv((c) => [...c, { role: 'user', text: userText }]);
    try {
      const t = await call();
      setTurn(t);
      setKase((k) => ({ ...k, status: t.case_status || k.status }));
      setConv((c) => [...c, { role: 'assistant', text: t.message, branch: t.branch }]);
      setUpload(false);
      setHint('');
    } catch (e) {
      setConv((c) => c.slice(0, -1));
      setErr(e.message);
      if (e.kind === 'stale') reload();
      else if (e.kind === 'network') setRetry(() => again);
      else if (e.kind === 'conflict') reload();
    } finally {
      setBusy(false);
    }
  }
  const sendReply = (quick_reply, label) => {
    const go = () => run(label, () => api.sendMessage(id, { quick_reply }), go);
    go();
  };
  const sendText = (t) => {
    const go = () => run(t, () => api.sendMessage(id, { text: t }), go);
    go();
    setText('');
  };
  const sendFile = (file, facts) => {
    const f = file || new Blob([JSON.stringify(facts)], { type: 'application/json' });
    if (!file) f.name = 'manual-facts.json';
    const go = () => run(`서류 올림: ${f.name || 'manual-facts.json'}`, () => api.uploadDocument(id, f, facts).then((d) => d.turn), go);
    go();
  };
  async function confirm() {
    setBusy(true);
    setErr(null);
    try {
      const d = await api.confirm(id, turn.ui.result?.code || turn.ui.result?.outcome || null);
      setKase(d.case);
      setHandoff({ ...d.handoff, confirmed_at: d.verdict?.confirmed_at });
    } catch (e) {
      setErr(e.message);
      if (e.kind === 'stale' || e.kind === 'conflict') reload();
    } finally {
      setBusy(false);
    }
  }
  const onAction = (action, key) => {
    if (action === 'UPLOAD') setUpload(true);
    else setHint(`오른쪽 판정 보드에서 '${key}' 항목을 고치거나 되돌려 주세요.`);
  };

  const q = turn.ui.question;
  const showEvidence = (turn.branch === 'REQUEST_EVIDENCE' || upload) && turn.ui.requested_documents.length > 0;
  let card = null;
  if (!confirmed) {
    if (turn.branch === 'FINAL_REVIEW') card = <FinalCard turn={turn} busy={busy} onConfirm={confirm} onRecheck={() => composer.current?.focus()} />;
    else if (turn.branch === 'UNSUPPORTED') card = <UnsupportedCard message={turn.message} pending={turn.ui.board.pending} />;
    else if (turn.branch === 'RESOLVE_CONFLICT' && turn.ui.conflicts.length) card = <ConflictCard conflicts={turn.ui.conflicts} disabled={busy} onReply={sendReply} onAction={onAction} />;
    else if (q && !showEvidence) card = <QuestionCard key={q.key} question={q} disabled={busy} onSend={sendReply} />;
    if (showEvidence) card = <EvidenceCard docs={turn.ui.requested_documents} disabled={busy} onUpload={sendFile} onText={sendText} />;
  } else if (turn.ui.result) card = <FinalCard turn={turn} confirmed handoff={handoff} />;

  return (
    <div className="case-layout">
      <div className="case-main">
        <div className="row between">
          <h2>{kase.summary.title} <span className="status-badge" data-status={kase.status}>{kase.summary.status_label || STATUS_LABEL[kase.status]}</span></h2>
          <span className="row">
            <a className="button button-small button-quiet" href="#/cases">← 목록</a>
            <a className="button button-small button-quiet" href={`#/cases/${id}/history`}>기록</a>
          </span>
        </div>
        <div className="chat" aria-live="polite">
          {conv.map((m, i) => <p key={i} className={`bubble ${m.role}`}>{m.text}</p>)}
          {busy && <p className="bubble assistant muted">판정 중…</p>}
        </div>
        {err && <p className="wd-alert" role="alert">{err} {retry && <button type="button" className="button button-small" onClick={retry}>다시 보내기</button>}</p>}
        {hint && <p className="wd-alert is-info">{hint}</p>}
        {card}
        {confirmed ? (
          <div className="row">
            <p className="muted">확정된 건입니다. 고치려면 기록에서 다시 여세요.</p>
            <button type="button" className="button button-small button-quiet" onClick={() => navigate(`/cases/${id}/history`)}>기록 보기</button>
          </div>
        ) : (
          <form className="composer" onSubmit={(e) => { e.preventDefault(); if (text.trim()) sendText(text.trim()); }}>
            <textarea ref={composer} className="wd-input" rows={2} disabled={busy} aria-label="메시지" placeholder="자유롭게 입력하거나 위에서 고르세요…"
              value={text} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (text.trim()) sendText(text.trim()); } }} />
            <button type="submit" className="button button-primary" disabled={busy || !text.trim()}>보내기</button>
          </form>
        )}
      </div>
      <Board board={turn.ui.board} locked={confirmed || busy} onReply={sendReply} />
    </div>
  );
}
