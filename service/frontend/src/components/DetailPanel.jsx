import { useState } from "react";
import { useApp } from "../AppContext.jsx";

export default function DetailPanel() {
  const {
    selectedClass,
    setDetailOpen,
    currentDomain,
    handleSaveClass,
    handleDeleteClass,
    handleAddProperty,
    setAddClassOpen,
    setAddClassPreSuper,
  } = useApp();

  const [editMode, setEditMode] = useState(false);
  const [editLabel, setEditLabel] = useState("");
  const [editComment, setEditComment] = useState("");
  const [propName, setPropName] = useState("");
  const [propLabel, setPropLabel] = useState("");
  const [propRange, setPropRange] = useState("xsd:string");
  const [saving, setSaving] = useState(false);
  const [addingProp, setAddingProp] = useState(false);

  const data = selectedClass;
  if (!data) return null;

  function enterEdit() {
    setEditLabel(data.label || data.name);
    setEditComment(data.comment || "");
    setEditMode(true);
  }

  function cancelEdit() {
    setEditMode(false);
  }

  async function onSave() {
    setSaving(true);
    try {
      await handleSaveClass({
        className: data.name,
        newLabel: editLabel,
        newComment: editComment,
        oldLabel: data.label || data.name,
        oldComment: data.comment || "",
      });
      setEditMode(false);
    } catch (err) {
      alert("Error saving: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    try {
      await handleDeleteClass(data);
    } catch (err) {
      alert("Error deleting: " + err.message);
    }
  }

  async function onAddProp() {
    if (!propName.trim()) { alert("Property name is required."); return; }
    const isObject = !propRange.startsWith("xsd:");
    setAddingProp(true);
    try {
      await handleAddProperty({
        domainClass: data.name,
        name: propName.trim(),
        label: propLabel.trim() || propName.trim(),
        range: propRange,
        isObject,
      });
      setPropName("");
      setPropLabel("");
      setPropRange("xsd:string");
    } catch (err) {
      alert("Error adding property: " + err.message);
    } finally {
      setAddingProp(false);
    }
  }

  const classOptions = currentDomain?.classes || [];

  return (
    <div id="detail-panel">
      <button id="btn-close-detail" className="close-btn" onClick={() => setDetailOpen(false)}>✕</button>

      {!editMode ? (
        <div id="detail-view">
          <h2 id="detail-name">{data.name || data.label}</h2>
          <p id="detail-comment" className="muted">{data.comment || "No description"}</p>
          {data.superclasses?.length > 0 && (
            <div id="detail-superclasses">Extends: {data.superclasses.join(", ")}</div>
          )}
          <h3>Properties</h3>
          <table id="detail-props">
            <thead><tr><th>Name</th><th>Type</th><th>Kind</th></tr></thead>
            <tbody>
              {data.properties?.length > 0
                ? data.properties.map(p => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td>{p.type}</td>
                    <td>{p.is_object ? "object" : "data"}</td>
                  </tr>
                ))
                : <tr><td colSpan="3" className="muted">No properties</td></tr>
              }
            </tbody>
          </table>
          <div className="detail-actions">
            <button className="btn-sm btn-primary" onClick={enterEdit}>✎ Edit</button>
            <button className="btn-sm btn-danger" onClick={onDelete}>🗑 Delete</button>
          </div>
        </div>
      ) : (
        <div id="detail-edit">
          <h3>Edit Class</h3>
          <label>
            Name
            <input type="text" value={data.name} disabled />
          </label>
          <label>
            Label
            <input type="text" value={editLabel} onChange={e => setEditLabel(e.target.value)} />
          </label>
          <label>
            Comment
            <textarea rows="3" value={editComment} onChange={e => setEditComment(e.target.value)} />
          </label>
          <div className="detail-actions">
            <button className="btn-sm btn-primary" onClick={onSave} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button className="btn-sm" onClick={cancelEdit}>Cancel</button>
          </div>

          <h3>Add Property</h3>
          <label>
            Name
            <input
              type="text"
              placeholder="camelCase"
              value={propName}
              onChange={e => setPropName(e.target.value)}
            />
          </label>
          <label>
            Label
            <input
              type="text"
              placeholder="Human-readable"
              value={propLabel}
              onChange={e => setPropLabel(e.target.value)}
            />
          </label>
          <label>
            Range
            <select value={propRange} onChange={e => setPropRange(e.target.value)}>
              <option value="xsd:string">xsd:string</option>
              <option value="xsd:integer">xsd:integer</option>
              <option value="xsd:decimal">xsd:decimal</option>
              <option value="xsd:boolean">xsd:boolean</option>
              <option value="xsd:date">xsd:date</option>
              <option value="xsd:dateTime">xsd:dateTime</option>
              {classOptions.map(c => (
                <option key={c.name} value={c.name}>{c.name} (object)</option>
              ))}
            </select>
          </label>
          <div className="detail-actions">
            <button className="btn-sm btn-primary" onClick={onAddProp} disabled={addingProp}>
              + Add Property
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
