import { useState } from 'react';
import { api } from '../api/index.js';
import { navigate } from '../lib/router.js';

const EXAMPLES = ['PP 사출 불량품이에요', '도금 라인 폐황산', '폐수처리 오니'];

export default function NewCasePage() {
  const [memo, setMemo] = useState('');
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState('kg');
  const [period, setPeriod] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  async function submit(withMemo) {
    setBusy(true);
    setErr('');
    try {
      const body = { memo: withMemo ? memo.trim() || null : null, quantity: quantity ? Number(quantity) : null, unit: quantity ? unit : null, period: period.trim() || null };
      const { case: c } = await api.createCase(body);
      navigate(`/cases/${c.id}`);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="wd-card narrow">
      <h2>새 문진</h2>
      <p className="bubble assistant">어떤 폐기물인지 아는 만큼 적어 주세요. 소재, 상태, 기름·약품이 묻었는지, 예전 신고 번호 등 무엇이든 좋아요.</p>
      <div className="row wrap">
        {EXAMPLES.map((x) => <button key={x} type="button" className="wd-chip" onClick={() => setMemo(x)}>{x}</button>)}
      </div>
      <textarea className="wd-input" rows={4} aria-label="폐기물 설명" value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="예) PP 사출 스크랩이에요. 고체예요." />
      <details>
        <summary>수량·발생 시기 (선택)</summary>
        <div className="row wrap">
          <label className="wd-field"><span>수량</span><input className="wd-input" type="number" min="0" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
          <label className="wd-field"><span>단위</span><input className="wd-input" value={unit} onChange={(e) => setUnit(e.target.value)} /></label>
          <label className="wd-field"><span>발생 시기</span><input className="wd-input" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="월 2회" /></label>
        </div>
      </details>
      {err && <p className="wd-alert" role="alert">{err}</p>}
      <div className="row">
        <button type="button" className="button button-primary" disabled={busy || !memo.trim()} onClick={() => submit(true)}>보내기</button>
        <button type="button" className="button button-quiet" disabled={busy} onClick={() => submit(false)}>질문부터 받을게요</button>
        <a className="button button-link" href="#/cases">취소</a>
      </div>
    </div>
  );
}
