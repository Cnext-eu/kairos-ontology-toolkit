import { useState, useEffect, useCallback } from "react";
import { AppContext } from "./AppContext.jsx";
import { apiFetch, buildHeaders, setAuthToken, setActiveRepo } from "./api.js";
import Sidebar from "./components/Sidebar.jsx";
import GraphPanel from "./components/GraphPanel.jsx";
import DetailPanel from "./components/DetailPanel.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import ContextMenu from "./components/ContextMenu.jsx";
import ProjectionModal from "./components/modals/ProjectionModal.jsx";
import AddClassModal from "./components/modals/AddClassModal.jsx";
import SaveModal from "./components/modals/SaveModal.jsx";
import ApplicationModelPanel from "./components/ApplicationModelPanel.jsx";

export default function App() {
  // ── Auth ─────────────────────────────────────────────────
  const [authUser, setAuthUser] = useState(null);
  const [oauthEnabled, setOauthEnabled] = useState(false);

  // ── Repos / domains ──────────────────────────────────────
  const [repos, setRepos] = useState([]);
  const [activeRepo, setActiveRepoState] = useState(null);
  const [allDomains, setAllDomains] = useState([]);
  const [currentDomain, setCurrentDomain] = useState(null);

  // ── Change tracking ───────────────────────────────────────
  const [pendingChanges, setPendingChanges] = useState([]);
  const [undoStack, setUndoStack] = useState([]);
  const [redoStack, setRedoStack] = useState([]);
  const isDirty = pendingChanges.length > 0;

  // ── UI state ──────────────────────────────────────────────
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedClass, setSelectedClass] = useState(null);
  const [validationStatus, setValidationStatus] = useState(null); // null | 'validating' | 'pass' | 'fail'

  // ── Modal state ───────────────────────────────────────────
  const [projectionOpen, setProjectionOpen] = useState(false);
  const [addClassOpen, setAddClassOpen] = useState(false);
  const [addClassPreSuper, setAddClassPreSuper] = useState("");
  const [saveOpen, setSaveOpen] = useState(false);

  // ── Context menu ──────────────────────────────────────────
  const [contextMenu, setContextMenu] = useState(null); // {x, y, classData}

  // ── Chat ──────────────────────────────────────────────────
  const [chatHistory, setChatHistory] = useState([]);
  const [pendingQuickPrompt, setPendingQuickPrompt] = useState(null);

  // ── Projection targets ────────────────────────────────────
  const [projectionTargets, setProjectionTargets] = useState([]);

  // ── Application models ───────────────────────────────────
  const [appModels, setAppModels] = useState([]);
  const [appModelOpen, setAppModelOpen] = useState(false);
  const [currentAppModel, setCurrentAppModel] = useState(null);   // { name, content }
  const [appModelLoading, setAppModelLoading] = useState(false);

  // ── Sync activeRepo into api module ──────────────────────
  useEffect(() => {
    setActiveRepo(activeRepo);
  }, [activeRepo]);

  // ── Init ──────────────────────────────────────────────────
  useEffect(() => {
    async function init() {
      try {
        const cfg = await (await fetch("/api/config")).json();
        if (cfg.github_token) setAuthToken("Bearer " + cfg.github_token);
        if (cfg.active_repo) {
          setActiveRepoState(cfg.active_repo);
          setActiveRepo(cfg.active_repo);
        }
        setOauthEnabled(!!cfg.oauth_enabled);
      } catch (_) { /* non-critical */ }

      await checkAuthStatus();
      await loadRepos();
      await loadProjectTargets();
      await loadAppModels();
    }
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Keyboard shortcuts ────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e) {
      if (e.ctrlKey && e.key === "z" && !e.shiftKey) { e.preventDefault(); handleUndo(); }
      if (e.ctrlKey && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
        e.preventDefault(); handleRedo();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [undoStack, redoStack]);

  // ── Dirty guard ───────────────────────────────────────────
  useEffect(() => {
    function onBeforeUnload(e) {
      if (isDirty) { e.preventDefault(); e.returnValue = ""; }
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [isDirty]);

  // ── Auth ──────────────────────────────────────────────────
  async function checkAuthStatus() {
    try {
      const data = await (await fetch("/api/auth/status", { credentials: "same-origin" })).json();
      setOauthEnabled(!!data.oauth_enabled);
      if (data.authenticated) {
        setAuthUser({ user: data.user, name: data.name, avatar: data.avatar });
        if (data.token) setAuthToken("Bearer " + data.token);
      } else {
        setAuthUser(null);
      }
    } catch (_) {
      setAuthUser(null);
    }
  }

  async function handleLogout() {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    } catch (_) { /* ok */ }
    setAuthUser(null);
  }

  // ── Repos ─────────────────────────────────────────────────
  async function loadRepos() {
    try {
      const data = await apiFetch("GET", "/api/repos/");
      setRepos(data);
      if (data.length === 1) {
        await selectRepo(data[0]);
      } else {
        // More than one repo available — load domains for the pre-configured active repo
        await loadDomains();
      }
    } catch (err) {
      console.error("Failed to load repos:", err);
      await loadDomains();
    }
  }

  async function selectRepo(repo) {
    setActiveRepoState(repo);
    setActiveRepo(repo);
    setChatHistory([]);
    setCurrentAppModel(null);
    await loadDomains(repo);
    await loadAppModels();
  }

  async function handleRepoChange(repoJson) {
    if (isDirty) {
      if (!window.confirm("You have unsaved changes. Switch repository anyway?")) return false;
      setPendingChanges([]);
      setUndoStack([]);
      setRedoStack([]);
    }
    if (!repoJson) {
      setActiveRepoState(null);
      setActiveRepo(null);
      setAllDomains([]);
      setCurrentDomain(null);
      return true;
    }
    const repo = JSON.parse(repoJson);
    await selectRepo(repo);
    return true;
  }

  // ── Domains ───────────────────────────────────────────────
  async function loadDomains(repoOverride) {
    try {
      const data = await apiFetch("GET", "/api/ontology/query");
      setAllDomains(data);
      if (data.length === 1) {
        setCurrentDomain(data[0]);
      }
    } catch (err) {
      console.error("Failed to load domains:", err);
      setAllDomains([]);
    }
  }

  async function handleDomainChange(domainName) {
    if (!domainName) {
      setCurrentDomain(null);
      setDetailOpen(false);
      return;
    }
    const domain = allDomains.find(d => d.domain === domainName) || null;
    setCurrentDomain(domain);
    setDetailOpen(false);
    setValidationStatus(null);
  }

  async function reloadCurrentDomain() {
    if (!currentDomain) return;
    try {
      const data = await apiFetch("GET", "/api/ontology/query");
      setAllDomains(data);
      const updated = data.find(d => d.domain === currentDomain.domain) || null;
      setCurrentDomain(updated);
    } catch (err) {
      console.error("Failed to reload domain:", err);
    }
  }

  // ── Projection targets ────────────────────────────────────
  async function loadProjectTargets() {
    try {
      const data = await apiFetch("GET", "/api/project/targets");
      setProjectionTargets(data.targets || []);
    } catch (_) { /* ok */ }
  }

  // ── Application models ────────────────────────────────────
  async function loadAppModels() {
    try {
      const data = await apiFetch("GET", "/api/application-models/");
      setAppModels(data);
    } catch (_) {
      setAppModels([]);
    }
  }

  async function handleAppModelChange(name) {
    if (!name) {
      setCurrentAppModel(null);
      setAppModelOpen(false);
      return;
    }
    setAppModelLoading(true);
    setAppModelOpen(true);
    try {
      const data = await apiFetch("GET", `/api/application-models/${encodeURIComponent(name.replace(".mmd", ""))}`);
      setCurrentAppModel({ name, content: data.content });
    } catch (err) {
      setCurrentAppModel({ name, content: `%% Error loading model: ${err.message}` });
    } finally {
      setAppModelLoading(false);
    }
  }

  // ── Validate ──────────────────────────────────────────────
  async function handleValidate() {
    if (!currentDomain) return;
    setValidationStatus("validating");
    try {
      const result = await apiFetch("POST", "/api/validate", {
        domain: currentDomain.domain.replace(".ttl", ""),
      });
      const ok = result.syntax.passed && result.shacl.passed;
      setValidationStatus(ok ? "pass" : "fail");
    } catch (_) {
      setValidationStatus("fail");
    }
  }

  // ── Undo / Redo ───────────────────────────────────────────
  async function handleUndo() {
    if (!undoStack.length) return;
    const entry = undoStack[undoStack.length - 1];
    try {
      await apiFetch("POST", "/api/ontology/change", {
        domain: entry.domain,
        action: entry.reverseAction,
        details: entry.reverseDetails,
      });
      setUndoStack(s => s.slice(0, -1));
      setRedoStack(s => [...s, {
        action: entry.reverseAction, domain: entry.domain, details: entry.reverseDetails,
        reverseAction: entry.action, reverseDetails: entry.details,
      }]);
      setPendingChanges(s => {
        const idx = [...s].reverse().findIndex(
          c => c.action === entry.action && c.domain === entry.domain
        );
        if (idx < 0) return s;
        const actualIdx = s.length - 1 - idx;
        return [...s.slice(0, actualIdx), ...s.slice(actualIdx + 1)];
      });
      await reloadCurrentDomain();
    } catch (err) {
      alert("Undo failed: " + err.message);
    }
  }

  async function handleRedo() {
    if (!redoStack.length) return;
    const entry = redoStack[redoStack.length - 1];
    try {
      await apiFetch("POST", "/api/ontology/change", {
        domain: entry.domain,
        action: entry.reverseAction,
        details: entry.reverseDetails,
      });
      setRedoStack(s => s.slice(0, -1));
      setUndoStack(s => [...s, {
        action: entry.reverseAction, domain: entry.domain, details: entry.reverseDetails,
        reverseAction: entry.action, reverseDetails: entry.details,
      }]);
      setPendingChanges(s => [...s, {
        action: entry.reverseAction, domain: entry.domain,
        details: entry.reverseDetails, timestamp: Date.now(),
      }]);
      await reloadCurrentDomain();
    } catch (err) {
      alert("Redo failed: " + err.message);
    }
  }

  // ── Class CRUD ────────────────────────────────────────────
  async function handleCreateClass({ name, label, comment, superclass }) {
    if (!currentDomain) return;
    const domain = currentDomain.domain.replace(".ttl", "");
    const details = { name, label: label || name, comment: comment || name };
    if (superclass) details.superclass = superclass;
    await apiFetch("POST", "/api/ontology/change", { domain, action: "add_class", details });
    setPendingChanges(s => [...s, { action: "add_class", domain, details, timestamp: Date.now() }]);
    setUndoStack(s => [...s, {
      action: "add_class", domain, details,
      reverseAction: "remove_class", reverseDetails: { class_name: name },
    }]);
    setRedoStack([]);
    await reloadCurrentDomain();
  }

  async function handleSaveClass({ className, newLabel, newComment, oldLabel, oldComment }) {
    const domain = currentDomain.domain.replace(".ttl", "");
    await apiFetch("POST", "/api/ontology/change", {
      domain, action: "modify_class",
      details: { class_name: className, new_label: newLabel || undefined, new_comment: newComment || undefined },
    });
    setPendingChanges(s => [...s, {
      action: "modify_class", domain, details: { class_name: className }, timestamp: Date.now(),
    }]);
    setUndoStack(s => [...s, {
      action: "modify_class", domain, details: { class_name: className },
      reverseAction: "modify_class",
      reverseDetails: { class_name: className, new_label: oldLabel, new_comment: oldComment },
    }]);
    setRedoStack([]);
    await reloadCurrentDomain();
  }

  async function handleDeleteClass(classData) {
    if (!window.confirm(`Delete class "${classData.name}"? This cannot be undone.`)) return;
    const domain = currentDomain.domain.replace(".ttl", "");
    await apiFetch("POST", "/api/ontology/change", {
      domain, action: "remove_class", details: { class_name: classData.name },
    });
    setPendingChanges(s => [...s, {
      action: "remove_class", domain, details: { class_name: classData.name }, timestamp: Date.now(),
    }]);
    setUndoStack(s => [...s, {
      action: "remove_class", domain, details: { class_name: classData.name },
      reverseAction: "add_class",
      reverseDetails: { name: classData.name, label: classData.label || classData.name, comment: classData.comment || "" },
    }]);
    setRedoStack([]);
    setDetailOpen(false);
    setSelectedClass(null);
    await reloadCurrentDomain();
  }

  async function handleAddProperty({ domainClass, name, label, range, isObject }) {
    const domain = currentDomain.domain.replace(".ttl", "");
    await apiFetch("POST", "/api/ontology/change", {
      domain, action: "add_property",
      details: { name, label: label || name, domain_class: domainClass, range, is_object: isObject },
    });
    setPendingChanges(s => [...s, {
      action: "add_property", domain,
      details: { class_name: domainClass, property_name: name }, timestamp: Date.now(),
    }]);
    setUndoStack(s => [...s, {
      action: "add_property", domain, details: { class_name: domainClass, property_name: name },
      reverseAction: "remove_property", reverseDetails: { property_name: name },
    }]);
    setRedoStack([]);
    await reloadCurrentDomain();
  }

  // ── Save ──────────────────────────────────────────────────
  async function handleSave({ message, createPr }) {
    const res = await apiFetch("POST", "/api/ontology/batch-apply", {
      changes: pendingChanges.map(c => ({ domain: c.domain, action: c.action, details: c.details })),
      message,
      create_pr: createPr,
    });
    setPendingChanges([]);
    setUndoStack([]);
    setRedoStack([]);
    await reloadCurrentDomain();
    return res;
  }

  // ── Chat quick-prompt ─────────────────────────────────────
  const sendQuickPrompt = useCallback((text) => {
    setChatOpen(true);
    setPendingQuickPrompt(text);
  }, []);

  // ── Context value ─────────────────────────────────────────
  const ctx = {
    authUser, oauthEnabled, handleLogout,
    repos, activeRepo, handleRepoChange,
    allDomains, currentDomain, handleDomainChange,
    pendingChanges, undoStack, redoStack, isDirty,
    handleUndo, handleRedo, handleSave,
    handleValidate, validationStatus,
    handleCreateClass, handleSaveClass, handleDeleteClass, handleAddProperty,
    selectedClass, setSelectedClass,
    detailOpen, setDetailOpen,
    chatOpen, setChatOpen,
    sidebarOpen, setSidebarOpen,
    projectionOpen, setProjectionOpen,
    addClassOpen, setAddClassOpen, addClassPreSuper, setAddClassPreSuper,
    saveOpen, setSaveOpen,
    contextMenu, setContextMenu,
    chatHistory, setChatHistory,
    pendingQuickPrompt, setPendingQuickPrompt,
    sendQuickPrompt,
    projectionTargets,
    appModels, appModelOpen, setAppModelOpen,
    currentAppModel, appModelLoading, handleAppModelChange,
  };

  return (
    <AppContext.Provider value={ctx}>
      <div id="main">
        <Sidebar />
        <button id="btn-menu" title="Toggle menu" onClick={() => setSidebarOpen(o => !o)}>☰</button>
        <div id="workspace">
          <GraphPanel />
          {detailOpen && selectedClass && <DetailPanel />}
        </div>
        {chatOpen && <ChatPanel />}
        {appModelOpen && currentAppModel && (
          <ApplicationModelPanel
            name={currentAppModel.name}
            content={currentAppModel.content}
            onClose={() => { setAppModelOpen(false); setCurrentAppModel(null); }}
          />
        )}
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          classData={contextMenu.classData}
          onClose={() => setContextMenu(null)}
        />
      )}

      {projectionOpen && <ProjectionModal />}
      {addClassOpen && <AddClassModal />}
      {saveOpen && <SaveModal />}
    </AppContext.Provider>
  );
}
