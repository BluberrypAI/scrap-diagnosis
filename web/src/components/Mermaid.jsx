import { useEffect, useRef, useState } from 'react';

let seq = 0;

/** mermaid 그래프(개발자 화면 전용). 노드 클릭은 window.ruleClick(id)로 받는다. */
export default function Mermaid({ code, onNodeClick }) {
  const ref = useRef(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    let alive = true;
    window.ruleClick = (id) => onNodeClick && onNodeClick(id);
    (async () => {
      try {
        const { default: mermaid } = await import('mermaid');
        mermaid.initialize({ startOnLoad: false, securityLevel: 'loose', flowchart: { htmlLabels: true, useMaxWidth: false } });
        const { svg, bindFunctions } = await mermaid.render(`mmd-${++seq}`, code);
        if (!alive || !ref.current) return;
        ref.current.innerHTML = svg;
        bindFunctions?.(ref.current);
        setErr('');
      } catch (e) {
        if (alive) setErr(String(e?.message || e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [code, onNodeClick]);

  return (
    <>
      {err && <p className="wd-alert" role="alert">그래프를 그리지 못했어요: {err}</p>}
      <div className="mermaid-box" ref={ref} />
    </>
  );
}
