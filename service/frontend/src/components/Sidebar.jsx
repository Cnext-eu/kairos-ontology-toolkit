import { useState } from "react";
import { useApp } from "../AppContext.jsx";
import { setAuthToken } from "../api.js";

export default function Sidebar() {
  const {
    authUser, oauthEnabled, handleLogout,
    repos, activeRepo, handleRepoChange,
    allDomains, currentDomain, handleDomainChange,
    pendingChanges, undoStack, redoStack, isDirty,
    handleUndo, handleRedo,
    handleValidate, validationStatus,
    sidebarOpen,
    setAddClassOpen, setAddClassPreSuper,
    setSaveOpen, setProjectionOpen,
    setChatOpen, chatOpen,
    chatTriggerRef, sendQuickPrompt,
    appModels, currentAppModel, appModelLoading, handleAppModelChange,
  } = useApp();

  function onRepoChange(e) {
    handleRepoChange(e.target.value || null);
  }

  function onDomainChange(e) {
    handleDomainChange(e.target.value || "");
  }

  const [patInput, setPatInput] = useState("");
  const [patSaved, setPatSaved] = useState(false);

  function savePat() {
    const tok = patInput.trim();
    if (!tok) return;
    setAuthToken("Bearer " + tok);
    setPatSaved(true);
    setPatInput("");
  }

  function repoSelectValue() {
    if (!activeRepo) return "";
    return JSON.stringify({ owner: activeRepo.owner, name: activeRepo.name });
  }

  function domainSelectValue() {
    return currentDomain?.domain || "";
  }

  function validationBadge() {
    if (!validationStatus || validationStatus === null) return null;
    if (validationStatus === "validating") return <span className="badge">Validating…</span>;
    if (validationStatus === "pass") return <span className="badge pass">✓ Valid</span>;
    return <span className="badge fail">✗ Invalid</span>;
  }

  return (
    <nav id="sidebar" className={sidebarOpen ? "" : "collapsed"}>
      <div className="sidebar-header">
        <h1>Kairos Ontology Hub</h1>
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-section">
        <div className="sidebar-section-title">Repository</div>
        <div className="sidebar-repo-info">
          <span className={`repo-dot ${activeRepo ? "connected" : "disconnected"}`} />
          <span className="sidebar-repo-label">
            {activeRepo ? `${activeRepo.owner}/${activeRepo.name}` : "No repo selected"}
          </span>
        </div>
        <select
          className="sidebar-select"
          title="Select repository"
          value={repoSelectValue()}
          onChange={onRepoChange}
        >
          <option value="">— select repo —</option>
          {repos.map(r => (
            <option key={`${r.owner}/${r.name}`} value={JSON.stringify({ owner: r.owner, name: r.name })}>
              {r.name.replace("-ontology-hub", "")}
            </option>
          ))}
        </select>
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-section">
        <div className="sidebar-section-title">Domain</div>
        <select
          className="sidebar-select"
          value={domainSelectValue()}
          onChange={onDomainChange}
        >
          <option value="">— select domain —</option>
          {allDomains.map(d => (
            <option key={d.domain} value={d.domain}>
              {d.domain.replace(".ttl", "")}
            </option>
          ))}
        </select>
        <input
          id="search-input"
          className="sidebar-search"
          type="text"
          placeholder="Search classes…"
          onChange={e => {
            window.__kairosSearch?.(e.target.value);
          }}
        />
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-section">
        <div className="sidebar-section-title">Model</div>
        <button className="sidebar-btn" onClick={() => { setAddClassPreSuper(""); setAddClassOpen(true); }}>
          ＋ New Class
        </button>
        <button className="sidebar-btn" onClick={handleValidate} disabled={!currentDomain}>
          ✓ Validate
        </button>
        {validationBadge()}
        <button className="sidebar-btn" onClick={handleUndo} disabled={!undoStack.length}>
          ↩ Undo
        </button>
        <button className="sidebar-btn" onClick={handleRedo} disabled={!redoStack.length}>
          ↪ Redo
        </button>
        {isDirty && (
          <button className="sidebar-btn sb-save" onClick={() => setSaveOpen(true)}>
            💾 Save Changes
          </button>
        )}
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-section">
        <div className="sidebar-section-title">Application Models</div>
        <select
          className="sidebar-select"
          value={currentAppModel?.name || ""}
          onChange={e => handleAppModelChange(e.target.value || null)}
          disabled={appModelLoading}
        >
          <option value="">— select model —</option>
          {appModels.map(m => (
            <option key={m.name} value={m.name}>
              {m.name.replace(".mmd", "")}
            </option>
          ))}
        </select>
        {appModelLoading && <span className="badge">Loading…</span>}
        {appModels.length === 0 && (
          <span className="auth-hint">
            No models found. Add <code>.mmd</code> files to <code>output/medallion/silver/</code> in your repo.
          </span>
        )}
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-section">
        <div className="sidebar-section-title">Project</div>
        <button className="sidebar-btn" onClick={() => setProjectionOpen(true)}>
          ⚙ Generate Projections
        </button>
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-section">
        <div className="sidebar-section-title">Ask AI</div>
        <button className="sidebar-btn" onClick={() => sendQuickPrompt(
          "Explain the currently loaded ontology domain in detail. List all classes, their properties, and relationships."
        )}>
          💡 Explain this domain
        </button>
        <button className="sidebar-btn" onClick={() => sendQuickPrompt(
          "Suggest improvements for this ontology domain. Look for missing labels, incomplete properties, naming issues, and structural problems."
        )}>
          🔍 Suggest improvements
        </button>
        <button className="sidebar-btn" onClick={() => {
          setChatOpen(true);
          setTimeout(() => document.getElementById("chat-input")?.focus(), 50);
        }}>
          💬 Ask a question
        </button>
      </div>

      <div className="sidebar-section" style={{ marginTop: "auto" }}>
        <div className="sidebar-divider" />
        <div className="sidebar-auth">
          {/* OAuth login — shown when GitHub OAuth App is configured */}
          {!authUser && oauthEnabled && (
            <div id="auth-logged-out">
              <button className="sidebar-btn sb-login" onClick={() => { window.location.href = "/api/auth/login"; }}>
                🔑 Login with GitHub
              </button>
              <span className="auth-hint">Uses your Copilot licence</span>
            </div>
          )}

          {/* PAT fallback — shown when OAuth is not configured */}
          {!authUser && !oauthEnabled && (
            <div id="auth-pat">
              {patSaved ? (
                <div className="auth-pat-saved">
                  <span className="auth-hint">✓ Token set for this session</span>
                  <button className="sidebar-btn" onClick={() => { setPatSaved(false); setAuthToken(null); }}>
                    Clear token
                  </button>
                </div>
              ) : (
                <>
                  <div className="auth-pat-label">GitHub token for AI chat</div>
                  <div className="auth-pat-row">
                    <input
                      className="auth-pat-input"
                      type="password"
                      placeholder="ghp_…"
                      value={patInput}
                      onChange={e => setPatInput(e.target.value)}
                      onKeyDown={e => e.key === "Enter" && savePat()}
                    />
                    <button className="sidebar-btn" onClick={savePat} disabled={!patInput.trim()}>
                      Set
                    </button>
                  </div>
                  <span className="auth-hint">Needs <code>models:read</code> scope</span>
                </>
              )}
            </div>
          )}

          {/* Logged-in state (OAuth) */}
          {authUser && (
            <div id="auth-logged-in">
              <div className="auth-user-row">
                {authUser.avatar && <img className="auth-avatar" src={authUser.avatar} alt="" />}
                <span className="auth-username">{authUser.name || authUser.user}</span>
              </div>
              <button className="sidebar-btn sb-logout" onClick={handleLogout}>Logout</button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
