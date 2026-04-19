import { useState } from "react";
import { useApp } from "../../AppContext.jsx";

export default function AddClassModal() {
  const { setAddClassOpen, addClassPreSuper, currentDomain, handleCreateClass } = useApp();
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [comment, setComment] = useState("");
  const [superclass, setSuperclass] = useState(addClassPreSuper || "");
  const [creating, setCreating] = useState(false);

  function reset() {
    setName(""); setLabel(""); setComment(""); setSuperclass("");
  }

  async function onCreate() {
    if (!name.trim()) { alert("Class name is required."); return; }
    setCreating(true);
    try {
      await handleCreateClass({ name: name.trim(), label: label.trim(), comment: comment.trim(), superclass });
      reset();
      setAddClassOpen(false);
    } catch (err) {
      alert("Error creating class: " + err.message);
    } finally {
      setCreating(false);
    }
  }

  const classes = currentDomain?.classes || [];

  return (
    <div id="add-class-overlay" onClick={e => e.target === e.currentTarget && setAddClassOpen(false)}>
      <div id="add-class-modal" className="modal-box">
        <div className="modal-box-header">
          <span>New Class</span>
          <button className="close-btn" onClick={() => setAddClassOpen(false)}>✕</button>
        </div>
        <div className="modal-box-body">
          <label>
            Name
            <input type="text" placeholder="PascalCase" value={name} onChange={e => setName(e.target.value)} />
          </label>
          <label>
            Label
            <input type="text" placeholder="Human-readable label" value={label} onChange={e => setLabel(e.target.value)} />
          </label>
          <label>
            Comment
            <textarea rows="2" placeholder="Description" value={comment} onChange={e => setComment(e.target.value)} />
          </label>
          <label>
            Superclass
            <select value={superclass} onChange={e => setSuperclass(e.target.value)}>
              <option value="">(none)</option>
              {classes.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <div className="detail-actions">
            <button className="btn-sm btn-primary" onClick={onCreate} disabled={creating}>
              {creating ? "Creating…" : "Create"}
            </button>
            <button className="btn-sm" onClick={() => setAddClassOpen(false)}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}
