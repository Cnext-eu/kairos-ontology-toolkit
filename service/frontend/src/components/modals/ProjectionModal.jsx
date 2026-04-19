import { useState } from "react";
import { apiFetch } from "../../api.js";
import { useApp } from "../../AppContext.jsx";

export default function ProjectionModal() {
  const { setProjectionOpen, currentDomain, projectionTargets } = useApp();
  const [selected, setSelected] = useState(new Set(projectionTargets));
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  function toggle(target) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(target) ? next.delete(target) : next.add(target);
      return next;
    });
  }

  async function onGenerate() {
    if (!currentDomain) { setResult("Select a domain first."); return; }
    if (!selected.size) { setResult("Select at least one target."); return; }
    setLoading(true);
    setResult(null);
    try {
      const res = await apiFetch("POST", "/api/project", {
        domain: currentDomain.domain.replace(".ttl", ""),
        targets: [...selected],
      });
      setResult(res);
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setLoading(false);
    }
  }

  function renderResult() {
    if (!result) return null;
    if (typeof result === "string") return <p>{result}</p>;
    if (result.error) return <p style={{ color: "#f85149" }}>Error: {result.error}</p>;
    return Object.entries(result.targets || {}).map(([target, files]) => (
      <div key={target}>
        <strong>{target}</strong>
        {Object.entries(files).map(([fname, content]) => (
          <pre key={fname}><code>// {fname}{"\n"}{content}</code></pre>
        ))}
      </div>
    ));
  }

  return (
    <div id="modal-overlay" onClick={e => e.target === e.currentTarget && setProjectionOpen(false)}>
      <div id="modal">
        <div id="modal-header">
          <span>Generate Projections</span>
          <button className="close-btn" onClick={() => setProjectionOpen(false)}>✕</button>
        </div>
        <div id="modal-body">
          <div id="target-checkboxes">
            {projectionTargets.map(t => (
              <label key={t}>
                <input
                  type="checkbox"
                  value={t}
                  checked={selected.has(t)}
                  onChange={() => toggle(t)}
                />
                {" "}{t}
              </label>
            ))}
          </div>
          <button id="btn-run-project" onClick={onGenerate} disabled={loading}>
            {loading ? "Generating…" : "Generate"}
          </button>
        </div>
        <div id="modal-result">{renderResult()}</div>
      </div>
    </div>
  );
}
