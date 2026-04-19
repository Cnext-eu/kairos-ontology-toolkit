import { useApp } from "../AppContext.jsx";

export default function ContextMenu({ x, y, classData, onClose }) {
  const { setSelectedClass, setDetailOpen, setAddClassPreSuper, setAddClassOpen, handleDeleteClass } = useApp();

  function enterEdit() {
    setSelectedClass(classData);
    setDetailOpen(true);
    onClose();
    // Defer so DetailPanel renders before trying to open edit mode
    setTimeout(() => {
      window.__kairosEnterEdit?.();
    }, 50);
  }

  function addSubclass() {
    setAddClassPreSuper(classData?.name || "");
    setAddClassOpen(true);
    onClose();
  }

  async function doDelete() {
    onClose();
    try {
      await handleDeleteClass(classData);
    } catch (err) {
      alert("Error deleting: " + err.message);
    }
  }

  return (
    <div
      id="context-menu"
      style={{ left: x, top: y, position: "fixed" }}
    >
      <button className="ctx-item" onClick={enterEdit}>✎ Edit</button>
      <button className="ctx-item" onClick={enterEdit}>＋ Property</button>
      <button className="ctx-item" onClick={addSubclass}>＋ Subclass</button>
      <button className="ctx-item ctx-danger" onClick={doDelete}>🗑 Delete</button>
    </div>
  );
}
