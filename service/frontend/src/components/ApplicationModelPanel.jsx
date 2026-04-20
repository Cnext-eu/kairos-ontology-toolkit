import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "default",
  securityLevel: "loose",
});

let _mmdCounter = 0;

export default function ApplicationModelPanel({ content, name, onClose }) {
  const containerRef = useRef(null);
  const [error, setError] = useState(null);
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    if (!content || !containerRef.current) return;

    setError(null);
    const id = `mmd-${++_mmdCounter}`;

    mermaid.render(id, content)
      .then(({ svg }) => {
        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      })
      .catch((err) => {
        setError(String(err));
      });
  }, [content]);

  return (
    <div id="app-model-panel">
      <div id="app-model-header">
        <span id="app-model-title">
          📐 {name ? name.replace(".mmd", "") : "Application Model"}
        </span>
        <div id="app-model-controls">
          <button
            className="sidebar-btn"
            title="Zoom out"
            onClick={() => setZoom(z => Math.max(0.25, z - 0.1))}
          >
            −
          </button>
          <span style={{ fontSize: "0.75rem", color: "#aaa", minWidth: "3rem", textAlign: "center" }}>
            {Math.round(zoom * 100)}%
          </span>
          <button
            className="sidebar-btn"
            title="Zoom in"
            onClick={() => setZoom(z => Math.min(4, z + 0.1))}
          >
            ＋
          </button>
          <button
            className="sidebar-btn"
            title="Reset zoom"
            onClick={() => setZoom(1)}
          >
            ↺
          </button>
          <button
            className="sidebar-btn"
            title="Close"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
      </div>

      <div id="app-model-body">
        {error ? (
          <div className="app-model-error">
            <strong>⚠ Diagram parse error</strong>
            <pre>{error}</pre>
          </div>
        ) : (
          <div
            id="app-model-svg-wrap"
            style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
            ref={containerRef}
          />
        )}
      </div>
    </div>
  );
}
