import { useState } from "react";
import { useApp } from "../../AppContext.jsx";

export default function SaveModal() {
  const { setSaveOpen, pendingChanges, handleSave } = useApp();
  const [message, setMessage] = useState(
    `ontology: ${pendingChanges.length} change(s)`
  );
  const [createPr, setCreatePr] = useState(true);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);

  const domains = new Set(pendingChanges.map(c => c.domain));

  async function onSave() {
    if (!message.trim()) { setResult({ error: "Commit message required." }); return; }
    setSaving(true);
    setResult(null);
    try {
      const res = await handleSave({ message: message.trim(), createPr });
      setResult({ success: true, prUrl: res.pr_url });
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div id="save-overlay" onClick={e => e.target === e.currentTarget && !saving && setSaveOpen(false)}>
      <div id="save-modal" className="modal-box">
        <div className="modal-box-header">
          <span>Save Changes</span>
          <button className="close-btn" onClick={() => setSaveOpen(false)}>✕</button>
        </div>
        <div className="modal-box-body">
          <p style={{ fontSize: 13, color: "#8b949e", marginBottom: 12 }}>
            <strong>
              {pendingChanges.length} change(s) across {domains.size} domain(s)
            </strong>
          </p>
          <label>
            Commit message
            <input
              type="text"
              placeholder="ontology: describe your changes"
              value={message}
              onChange={e => setMessage(e.target.value)}
              disabled={saving}
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
            <input
              type="checkbox"
              checked={createPr}
              onChange={e => setCreatePr(e.target.checked)}
              style={{ width: "auto", margin: 0 }}
              disabled={saving}
            />
            Create pull request
          </label>
          <div className="detail-actions" style={{ marginTop: 16 }}>
            <button className="btn-sm btn-primary" onClick={onSave} disabled={saving}>
              {saving ? "Saving…" : "💾 Save & Commit"}
            </button>
            <button className="btn-sm" onClick={() => setSaveOpen(false)} disabled={saving}>
              Cancel
            </button>
          </div>
          {result && (
            <div style={{ marginTop: 12, fontSize: 13 }}>
              {result.error && <span style={{ color: "#f85149" }}>❌ Error: {result.error}</span>}
              {result.success && (
                <span>
                  ✅ Saved successfully.{" "}
                  {result.prUrl && (
                    <a href={result.prUrl} target="_blank" rel="noreferrer" style={{ color: "#58a6ff" }}>
                      View PR
                    </a>
                  )}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
