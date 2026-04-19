/* Kairos Ontology Hub — main application logic */
(function () {
  "use strict";

  const API = "";  // same origin
  let AUTH = "Bearer dev-token";  // default; replaced by /api/config in dev mode

  // ── DOM refs ──────────────────────────────────────────────
  const repoSelect     = document.getElementById("repo-select");
  const domainSelect   = document.getElementById("domain-select");
  const searchInput    = document.getElementById("search-input");
  const btnToggleChat  = document.getElementById("btn-toggle-chat");
  const statusBadge    = document.getElementById("status-badge");
  const graphEmpty     = document.getElementById("graph-empty");
  const detailPanel    = document.getElementById("detail-panel");
  const btnCloseDetail = document.getElementById("btn-close-detail");
  const chatPanel      = document.getElementById("chat-panel");
  const btnCloseChat   = document.getElementById("btn-close-chat");
  const chatMessages   = document.getElementById("chat-messages");
  const chatInput      = document.getElementById("chat-input");
  const btnSend        = document.getElementById("btn-send");
  const modalOverlay   = document.getElementById("modal-overlay");
  const btnCloseModal  = document.getElementById("btn-close-modal");
  const targetCBs      = document.getElementById("target-checkboxes");
  const btnRunProject  = document.getElementById("btn-run-project");
  const modalResult    = document.getElementById("modal-result");
  const detailView     = document.getElementById("detail-view");
  const detailEdit     = document.getElementById("detail-edit");
  const btnEditClass   = document.getElementById("btn-edit-class");
  const btnDeleteClass = document.getElementById("btn-delete-class");
  const btnSaveClass   = document.getElementById("btn-save-class");
  const btnCancelEdit  = document.getElementById("btn-cancel-edit");
  const btnAddProp     = document.getElementById("btn-add-prop");
  const addClassOverlay   = document.getElementById("add-class-overlay");
  const btnCloseAddClass  = document.getElementById("btn-close-add-class");
  const btnCreateClass    = document.getElementById("btn-create-class");
  const btnCancelAddClass = document.getElementById("btn-cancel-add-class");
  const contextMenu       = document.getElementById("context-menu");
  const ctxEdit           = document.getElementById("ctx-edit");
  const ctxAddProp        = document.getElementById("ctx-add-prop");
  const ctxAddSub         = document.getElementById("ctx-add-sub");
  const ctxDelete         = document.getElementById("ctx-delete");
  const saveOverlay       = document.getElementById("save-overlay");
  const saveSummary       = document.getElementById("save-summary");
  const saveMessage       = document.getElementById("save-message");
  const saveCreatePr      = document.getElementById("save-create-pr");
  const btnDoSave         = document.getElementById("btn-do-save");
  const btnCloseSave      = document.getElementById("btn-close-save");
  const btnCancelSave     = document.getElementById("btn-cancel-save");
  const saveResult        = document.getElementById("save-result");

  // Sidebar refs
  const sidebar            = document.getElementById("sidebar");
  const btnMenu            = document.getElementById("btn-menu");
  const sbAddClass         = document.getElementById("sb-add-class");
  const sbValidate         = document.getElementById("sb-validate");
  const sbUndo             = document.getElementById("sb-undo");
  const sbRedo             = document.getElementById("sb-redo");
  const sbSave             = document.getElementById("sb-save");
  const sbProject          = document.getElementById("sb-project");
  const sbExplain          = document.getElementById("sb-explain");
  const sbSuggest          = document.getElementById("sb-suggest");
  const sbAskFree          = document.getElementById("sb-ask-free");
  const sbSwitchRepo       = document.getElementById("sb-switch-repo");
  const sidebarRepoName    = document.getElementById("sidebar-repo-name");
  const sidebarRepoStatus  = document.getElementById("sidebar-repo-status");

  // ── State ─────────────────────────────────────────────────
  let cy = null;
  let allDomains = [];       // [{domain, namespace, classes, relationships}]
  let currentDomain = null;
  let chatHistory = [];      // [{role, content}]
  let activeRepo = null;     // {owner, name, full_name, default_branch}
  let selectedClassData = null;
  let pendingChanges = [];   // [{action, domain, details, timestamp}]
  let isDirty = false;
  let undoStack = [];        // [{action, domain, details, reverseAction, reverseDetails}]
  let redoStack = [];

  // ── Helpers ───────────────────────────────────────────────
  function headers(extra) {
    const h = { "Authorization": AUTH, "Content-Type": "application/json" };
    if (activeRepo) {
      h["X-Kairos-Repo-Owner"] = activeRepo.owner;
      h["X-Kairos-Repo-Name"] = activeRepo.name;
    }
    return Object.assign(h, extra || {});
  }

  async function api(method, path, body) {
    const opts = { method, headers: headers() };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(API + path, opts);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  // ── Dirty-state tracking ──────────────────────────────────
  function updateDirtyState() {
    if (pendingChanges.length > 0) {
      isDirty = true;
      sbSave.classList.remove("hidden");
    } else {
      isDirty = false;
      sbSave.classList.add("hidden");
    }
    sbUndo.disabled = undoStack.length === 0;
    sbRedo.disabled = redoStack.length === 0;
  }

  // ── Save dialog ─────────────────────────────────────────
  function showSaveDialog() {
    const domains = new Set(pendingChanges.map(c => c.domain));
    saveSummary.textContent =
      pendingChanges.length + " change(s) across " + domains.size + " domain(s)";
    saveMessage.value = "ontology: " + pendingChanges.length + " changes";
    saveResult.innerHTML = "";
    btnDoSave.disabled = false;
    btnDoSave.textContent = "💾 Save & Commit";
    saveOverlay.classList.remove("hidden");
  }

  function hideSaveDialog() {
    saveOverlay.classList.add("hidden");
    saveResult.innerHTML = "";
  }

  async function onDoSave() {
    const message = saveMessage.value.trim();
    if (!message) { saveResult.textContent = "Commit message required."; return; }
    const createPr = saveCreatePr.checked;
    try {
      btnDoSave.disabled = true;
      btnDoSave.textContent = "Saving…";
      saveResult.innerHTML = "<em>Saving…</em>";
      const res = await api("POST", "/api/ontology/batch-apply", {
        changes: pendingChanges.map(c => ({
          domain: c.domain,
          action: c.action,
          details: c.details,
        })),
        message,
        create_pr: createPr,
      });
      let html = "✅ Saved successfully.";
      if (res.pr_url) {
        html += ' <a href="' + esc(res.pr_url) +
          '" target="_blank" style="color:#58a6ff;">View PR</a>';
      }
      saveResult.innerHTML = html;
      pendingChanges = [];
      undoStack = [];
      redoStack = [];
      updateDirtyState();
      await reloadCurrentDomain();
    } catch (err) {
      saveResult.innerHTML = "❌ Error: " + esc(err.message);
    } finally {
      btnDoSave.disabled = false;
      btnDoSave.textContent = "💾 Save & Commit";
    }
  }

  // ── Undo / Redo ─────────────────────────────────────────
  async function onUndo() {
    if (!undoStack.length) return;
    const entry = undoStack.pop();
    try {
      await api("POST", "/api/ontology/change", {
        domain: entry.domain,
        action: entry.reverseAction,
        details: entry.reverseDetails,
      });
      redoStack.push({
        action: entry.reverseAction, domain: entry.domain,
        details: entry.reverseDetails,
        reverseAction: entry.action,
        reverseDetails: entry.details,
      });
      // Remove the last matching entry from pendingChanges
      let idx = -1;
      for (let i = pendingChanges.length - 1; i >= 0; i--) {
        if (pendingChanges[i].action === entry.action &&
            pendingChanges[i].domain === entry.domain) {
          idx = i;
          break;
        }
      }
      if (idx >= 0) pendingChanges.splice(idx, 1);
      updateDirtyState();
      await reloadCurrentDomain();
    } catch (err) {
      alert("Undo failed: " + err.message);
      undoStack.push(entry);
    }
  }

  async function onRedo() {
    if (!redoStack.length) return;
    const entry = redoStack.pop();
    try {
      await api("POST", "/api/ontology/change", {
        domain: entry.domain,
        action: entry.reverseAction,
        details: entry.reverseDetails,
      });
      undoStack.push({
        action: entry.reverseAction, domain: entry.domain,
        details: entry.reverseDetails,
        reverseAction: entry.action,
        reverseDetails: entry.details,
      });
      pendingChanges.push({
        action: entry.reverseAction, domain: entry.domain,
        details: entry.reverseDetails, timestamp: Date.now(),
      });
      updateDirtyState();
      await reloadCurrentDomain();
    } catch (err) {
      alert("Redo failed: " + err.message);
      redoStack.push(entry);
    }
  }

  // ── Init ──────────────────────────────────────────────────
  async function init() {
    // Fetch server config (dev mode token, etc.)
    try {
      const cfg = await (await fetch(API + "/api/config")).json();
      if (cfg.github_token) {
        AUTH = "Bearer " + cfg.github_token;
      }
      if (cfg.active_repo) {
        activeRepo = cfg.active_repo;
      }
    } catch (_) { /* non-critical */ }

    initGraph();
    await loadRepos();
    loadProjectTargets();
    repoSelect.addEventListener("change", onRepoChange);
    domainSelect.addEventListener("change", onDomainChange);
    searchInput.addEventListener("input", onSearch);
    btnToggleChat.addEventListener("click", toggleChat);
    btnCloseChat.addEventListener("click", toggleChat);
    btnCloseDetail.addEventListener("click", () => detailPanel.classList.add("hidden"));
    btnCloseModal.addEventListener("click", () => modalOverlay.classList.add("hidden"));
    btnRunProject.addEventListener("click", onRunProject);
    btnEditClass.addEventListener("click", enterEditMode);
    btnDeleteClass.addEventListener("click", onDeleteClass);
    btnSaveClass.addEventListener("click", onSaveClass);
    btnCancelEdit.addEventListener("click", exitEditMode);
    btnAddProp.addEventListener("click", onAddProperty);
    btnCloseAddClass.addEventListener("click", hideAddClassDialog);
    btnCreateClass.addEventListener("click", onCreateClass);
    btnCancelAddClass.addEventListener("click", hideAddClassDialog);
    btnDoSave.addEventListener("click", onDoSave);
    btnCloseSave.addEventListener("click", hideSaveDialog);
    btnCancelSave.addEventListener("click", hideSaveDialog);

    // Sidebar buttons
    btnMenu.addEventListener("click", toggleSidebar);
    sbAddClass.addEventListener("click", showAddClassDialog);
    sbValidate.addEventListener("click", onValidate);
    sbUndo.addEventListener("click", onUndo);
    sbRedo.addEventListener("click", onRedo);
    sbSave.addEventListener("click", showSaveDialog);
    sbProject.addEventListener("click", () => modalOverlay.classList.remove("hidden"));
    sbSwitchRepo.addEventListener("click", () => { repoSelect.focus(); });
    sbExplain.addEventListener("click", () => sendQuickPrompt("Explain the currently loaded ontology domain in detail. List all classes, their properties, and relationships."));
    sbSuggest.addEventListener("click", () => sendQuickPrompt("Suggest improvements for this ontology domain. Look for missing labels, incomplete properties, naming issues, and structural problems."));
    sbAskFree.addEventListener("click", () => { if (chatPanel.classList.contains("hidden")) toggleChat(); chatInput.focus(); });

    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key === "z" && !e.shiftKey) { e.preventDefault(); onUndo(); }
      if (e.ctrlKey && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
        e.preventDefault(); onRedo();
      }
    });
    window.addEventListener("beforeunload", (e) => {
      if (isDirty) { e.preventDefault(); e.returnValue = ""; }
    });
    initChatResize();
    ctxEdit.addEventListener("click", () => {
      contextMenu.classList.add("hidden");
      showDetail(selectedClassData);
      enterEditMode();
    });
    ctxAddProp.addEventListener("click", () => {
      contextMenu.classList.add("hidden");
      showDetail(selectedClassData);
      enterEditMode();
    });
    ctxAddSub.addEventListener("click", () => {
      contextMenu.classList.add("hidden");
      showAddClassDialog(selectedClassData ? selectedClassData.name : "");
    });
    ctxDelete.addEventListener("click", () => {
      contextMenu.classList.add("hidden");
      onDeleteClass();
    });
    btnSend.addEventListener("click", sendChat);
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
  }

  // ── Sidebar ──────────────────────────────────────────────
  function toggleSidebar() {
    sidebar.classList.toggle("collapsed");
  }

  function updateSidebarRepo() {
    if (activeRepo && activeRepo.name) {
      sidebarRepoName.textContent = activeRepo.owner + "/" + activeRepo.name;
      sidebarRepoStatus.className = "repo-dot connected";
    } else {
      sidebarRepoName.textContent = "No repo selected";
      sidebarRepoStatus.className = "repo-dot disconnected";
    }
  }

  function sendQuickPrompt(text) {
    if (chatPanel.classList.contains("hidden")) toggleChat();
    chatInput.value = text;
    sendChat();
  }

  // ── Graph (Cytoscape) ────────────────────────────────────
  function initGraph() {
    cy = cytoscape({
      container: document.getElementById("cy"),
      style: [
        { selector: "node", style: {
          "label": "data(label)",
          "background-color": "#1f6feb",
          "color": "#c9d1d9",
          "text-valign": "bottom",
          "text-margin-y": 6,
          "font-size": 12,
          "width": 40,
          "height": 40,
          "border-width": 2,
          "border-color": "#58a6ff",
        }},
        { selector: "node.has-super", style: {
          "background-color": "#238636",
          "border-color": "#3fb950",
        }},
        { selector: "node:selected", style: {
          "border-color": "#f0883e",
          "border-width": 3,
        }},
        { selector: "edge", style: {
          "width": 2,
          "line-color": "#30363d",
          "target-arrow-color": "#30363d",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          "label": "data(label)",
          "font-size": 10,
          "color": "#484f58",
          "text-rotation": "autorotate",
          "text-margin-y": -8,
        }},
        { selector: "edge.inheritance", style: {
          "line-color": "#3fb950",
          "line-style": "dashed",
          "target-arrow-color": "#3fb950",
          "target-arrow-shape": "triangle",
        }},
        { selector: "node.modified", style: {
          "border-color": "#d29922",
          "border-width": 3,
          "border-style": "dashed",
        }},
        { selector: "node.new-node", style: {
          "border-color": "#3fb950",
          "border-width": 3,
          "border-style": "dashed",
        }},
      ],
      layout: { name: "grid" },
      minZoom: 0.3,
      maxZoom: 3,
    });
    cy.on("tap", "node", (e) => showDetail(e.target.data()));
    cy.on("tap", (e) => {
      if (e.target === cy) detailPanel.classList.add("hidden");
      contextMenu.classList.add("hidden");
    });
    cy.on("dbltap", (e) => {
      if (e.target === cy) showAddClassDialog();
    });
    cy.on("cxttap", "node", (e) => {
      e.originalEvent.preventDefault();
      selectedClassData = e.target.data();
      const pos = e.renderedPosition || e.originalEvent;
      const x = pos.x || e.originalEvent.clientX;
      const y = pos.y || e.originalEvent.clientY;
      contextMenu.style.left = x + "px";
      contextMenu.style.top = y + "px";
      contextMenu.classList.remove("hidden");
    });
    document.addEventListener("click", (e) => {
      if (!contextMenu.contains(e.target)) contextMenu.classList.add("hidden");
    });
  }

  function renderGraph(domainData) {
    cy.elements().remove();
    if (!domainData) return;

    const elements = [];
    const classMap = {};

    // Nodes
    for (const cls of domainData.classes) {
      classMap[cls.name] = cls;
      elements.push({
        group: "nodes",
        data: { id: cls.uri, label: cls.name, ...cls },
        classes: cls.superclasses && cls.superclasses.length > 0 ? "has-super" : "",
      });
    }

    // Inheritance edges
    for (const cls of domainData.classes) {
      if (cls.superclasses) {
        for (const sup of cls.superclasses) {
          const parent = domainData.classes.find(c => c.name === sup);
          if (parent) {
            elements.push({
              group: "edges",
              data: { source: cls.uri, target: parent.uri, label: "subClassOf" },
              classes: "inheritance",
            });
          }
        }
      }
    }

    // Relationship edges
    if (domainData.relationships) {
      for (const rel of domainData.relationships) {
        const srcCls = domainData.classes.find(c => c.name === rel.domain || c.uri === rel.domain);
        const tgtCls = domainData.classes.find(c => c.name === rel.range || c.uri === rel.range);
        if (srcCls && tgtCls) {
          elements.push({
            group: "edges",
            data: { source: srcCls.uri, target: tgtCls.uri, label: rel.name },
          });
        }
      }
    }

    cy.add(elements);
    cy.layout({
      name: "cose",
      animate: true,
      animationDuration: 500,
      nodeRepulsion: 8000,
      idealEdgeLength: 120,
      padding: 40,
    }).run();

    graphEmpty.classList.add("hidden");

    for (const change of pendingChanges) {
      const name = change.details.class_name || change.details.name;
      if (!name) continue;
      const node = cy.nodes().filter(n => n.data("name") === name);
      if (change.action === "add_class") {
        node.addClass("new-node");
      } else {
        node.addClass("modified");
      }
    }
  }

  // ── Add-class dialog ────────────────────────────────────
  function showAddClassDialog(preSelectedSuper) {
    const superSelect = document.getElementById("new-class-super");
    superSelect.innerHTML = '<option value="">(none)</option>';
    if (currentDomain) {
      for (const cls of currentDomain.classes) {
        const opt = document.createElement("option");
        opt.value = cls.name;
        opt.textContent = cls.name;
        superSelect.appendChild(opt);
      }
    }
    if (preSelectedSuper) superSelect.value = preSelectedSuper;
    addClassOverlay.classList.remove("hidden");
  }

  function hideAddClassDialog() {
    addClassOverlay.classList.add("hidden");
    document.getElementById("new-class-name").value = "";
    document.getElementById("new-class-label").value = "";
    document.getElementById("new-class-comment").value = "";
    document.getElementById("new-class-super").value = "";
  }

  async function onCreateClass() {
    if (!currentDomain) return;
    const domain = domainSelect.value.replace(".ttl", "");
    const name = document.getElementById("new-class-name").value.trim();
    const label = document.getElementById("new-class-label").value.trim();
    const comment = document.getElementById("new-class-comment").value.trim();
    const superclass = document.getElementById("new-class-super").value;

    if (!name) { alert("Class name is required."); return; }

    const details = {
      name,
      label: label || name,
      comment: comment || name,
    };
    if (superclass) details.superclass = superclass;

    try {
      btnCreateClass.disabled = true;
      btnCreateClass.textContent = "Creating…";
      await api("POST", "/api/ontology/change", {
        domain,
        action: "add_class",
        details,
      });
      pendingChanges.push({ action: "add_class", domain, details, timestamp: Date.now() });
      undoStack.push({
        action: "add_class", domain, details,
        reverseAction: "remove_class",
        reverseDetails: { class_name: name },
      });
      redoStack = [];
      hideAddClassDialog();
      updateDirtyState();
      await reloadCurrentDomain();
    } catch (err) {
      alert("Error creating class: " + err.message);
    } finally {
      btnCreateClass.disabled = false;
      btnCreateClass.textContent = "Create";
    }
  }

  // ── Repo loading ──────────────────────────────────────────
  async function loadRepos() {
    try {
      const repos = await api("GET", "/api/repos/");
      repoSelect.innerHTML = '<option value="">— select repo —</option>';
      for (const r of repos) {
        const opt = document.createElement("option");
        opt.value = JSON.stringify({ owner: r.owner, name: r.name });
        opt.textContent = r.name.replace("-ontology-hub", "");
        repoSelect.appendChild(opt);
      }
      // Auto-select if only one repo or if active repo matches
      if (repos.length === 1) {
        repoSelect.selectedIndex = 1;
        onRepoChange();
      } else if (activeRepo && activeRepo.name) {
        for (let i = 0; i < repoSelect.options.length; i++) {
          if (repoSelect.options[i].value.includes(activeRepo.name)) {
            repoSelect.selectedIndex = i;
            onRepoChange();
            break;
          }
        }
      }
    } catch (err) {
      console.error("Failed to load repos:", err);
      repoSelect.innerHTML = '<option value="">Error loading repos</option>';
      // Fall back to loading domains from default config
      await loadDomains();
    }
    updateSidebarRepo();
  }

  function onRepoChange() {
    const val = repoSelect.value;
    if (isDirty) {
      if (!confirm("You have unsaved changes. Switch repository anyway?")) {
        // Restore previous selection
        if (activeRepo) {
          for (let i = 0; i < repoSelect.options.length; i++) {
            if (repoSelect.options[i].value.includes(activeRepo.name)) {
              repoSelect.selectedIndex = i;
              break;
            }
          }
        }
        return;
      }
      pendingChanges = [];
      undoStack = [];
      redoStack = [];
      updateDirtyState();
    }
    if (!val) {
      activeRepo = null;
      allDomains = [];
      domainSelect.innerHTML = '<option value="">— select repo first —</option>';
      cy.elements().remove();
      graphEmpty.textContent = "Select a repository to begin";
      graphEmpty.classList.remove("hidden");
      return;
    }
    activeRepo = JSON.parse(val);
    chatHistory = [];  // reset chat on repo switch
    updateSidebarRepo();
    loadDomains();
  }

  // ── Domain loading ────────────────────────────────────────
  async function loadDomains() {
    try {
      allDomains = await api("GET", "/api/ontology/query");
      domainSelect.innerHTML = '<option value="">— select domain —</option>';
      for (const d of allDomains) {
        const opt = document.createElement("option");
        opt.value = d.domain;
        opt.textContent = d.domain.replace(".ttl", "");
        domainSelect.appendChild(opt);
      }
      if (allDomains.length === 1) {
        domainSelect.value = allDomains[0].domain;
        onDomainChange();
      }
    } catch (err) {
      console.error("Failed to load domains:", err);
      domainSelect.innerHTML = '<option value="">Error loading</option>';
    }
  }

  function onDomainChange() {
    const name = domainSelect.value;
    currentDomain = allDomains.find(d => d.domain === name) || null;
    detailPanel.classList.add("hidden");
    statusBadge.classList.add("hidden");
    if (currentDomain) {
      renderGraph(currentDomain);
    } else {
      cy.elements().remove();
      graphEmpty.classList.remove("hidden");
    }
  }

  // ── Search ────────────────────────────────────────────────
  function onSearch() {
    if (!cy) return;
    const term = searchInput.value.toLowerCase();
    cy.nodes().forEach(n => {
      const match = !term || n.data("label").toLowerCase().includes(term)
        || (n.data("comment") || "").toLowerCase().includes(term);
      n.style("opacity", match ? 1 : 0.15);
    });
  }

  // ── Detail panel ──────────────────────────────────────────
  function showDetail(data) {
    selectedClassData = data;
    document.getElementById("detail-name").textContent = data.name || data.label;
    document.getElementById("detail-comment").textContent = data.comment || "No description";

    const superDiv = document.getElementById("detail-superclasses");
    if (data.superclasses && data.superclasses.length) {
      superDiv.textContent = "Extends: " + data.superclasses.join(", ");
    } else {
      superDiv.textContent = "";
    }

    const tbody = document.querySelector("#detail-props tbody");
    tbody.innerHTML = "";
    if (data.properties && data.properties.length) {
      for (const p of data.properties) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(p.name)}</td><td>${esc(p.type)}</td><td>${p.is_object ? "object" : "data"}</td>`;
        tbody.appendChild(tr);
      }
    } else {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="3" class="muted">No properties</td>';
      tbody.appendChild(tr);
    }

    detailView.classList.remove("hidden");
    detailEdit.classList.add("hidden");
    detailPanel.classList.remove("hidden");

    // Populate range dropdown with class URIs for object properties
    const rangeSelect = document.getElementById("add-prop-range");
    [...rangeSelect.options].forEach(opt => {
      if (!opt.value.startsWith("xsd:")) opt.remove();
    });
    if (currentDomain) {
      for (const cls of currentDomain.classes) {
        const opt = document.createElement("option");
        opt.value = cls.name;
        opt.textContent = cls.name + " (object)";
        rangeSelect.appendChild(opt);
      }
    }
  }

  // ── Edit workflow ────────────────────────────────────────
  function enterEditMode() {
    if (!selectedClassData) return;
    document.getElementById("edit-class-name").value = selectedClassData.name;
    document.getElementById("edit-class-label").value =
      selectedClassData.label || selectedClassData.name;
    document.getElementById("edit-class-comment").value =
      selectedClassData.comment || "";
    detailView.classList.add("hidden");
    detailEdit.classList.remove("hidden");
  }

  function exitEditMode() {
    detailView.classList.remove("hidden");
    detailEdit.classList.add("hidden");
  }

  async function onSaveClass() {
    if (!selectedClassData || !currentDomain) return;
    const domain = domainSelect.value.replace(".ttl", "");
    const newLabel = document.getElementById("edit-class-label").value.trim();
    const newComment = document.getElementById("edit-class-comment").value.trim();
    const oldLabel = selectedClassData.label || selectedClassData.name;
    const oldComment = selectedClassData.comment || "";

    try {
      btnSaveClass.disabled = true;
      btnSaveClass.textContent = "Saving…";
      await api("POST", "/api/ontology/change", {
        domain,
        action: "modify_class",
        details: {
          class_name: selectedClassData.name,
          new_label: newLabel || undefined,
          new_comment: newComment || undefined,
        },
      });
      pendingChanges.push({
        action: "modify_class", domain,
        details: { class_name: selectedClassData.name },
        timestamp: Date.now(),
      });
      undoStack.push({
        action: "modify_class", domain,
        details: { class_name: selectedClassData.name },
        reverseAction: "modify_class",
        reverseDetails: {
          class_name: selectedClassData.name,
          new_label: oldLabel,
          new_comment: oldComment,
        },
      });
      redoStack = [];
      exitEditMode();
      updateDirtyState();
      await reloadCurrentDomain();
    } catch (err) {
      alert("Error saving: " + err.message);
    } finally {
      btnSaveClass.disabled = false;
      btnSaveClass.textContent = "Save";
    }
  }

  async function onDeleteClass() {
    if (!selectedClassData || !currentDomain) return;
    if (!confirm(`Delete class "${selectedClassData.name}"? This cannot be undone.`)) return;
    const domain = domainSelect.value.replace(".ttl", "");
    const deletedName = selectedClassData.name;
    const deletedLabel = selectedClassData.label || selectedClassData.name;
    const deletedComment = selectedClassData.comment || "";
    try {
      await api("POST", "/api/ontology/change", {
        domain,
        action: "remove_class",
        details: { class_name: deletedName },
      });
      pendingChanges.push({
        action: "remove_class", domain,
        details: { class_name: deletedName },
        timestamp: Date.now(),
      });
      undoStack.push({
        action: "remove_class", domain,
        details: { class_name: deletedName },
        reverseAction: "add_class",
        reverseDetails: {
          name: deletedName,
          label: deletedLabel,
          comment: deletedComment,
        },
      });
      redoStack = [];
      detailPanel.classList.add("hidden");
      selectedClassData = null;
      updateDirtyState();
      await reloadCurrentDomain();
    } catch (err) {
      alert("Error deleting: " + err.message);
    }
  }

  async function onAddProperty() {
    if (!selectedClassData || !currentDomain) return;
    const domain = domainSelect.value.replace(".ttl", "");
    const name = document.getElementById("add-prop-name").value.trim();
    const label = document.getElementById("add-prop-label").value.trim();
    const range = document.getElementById("add-prop-range").value;

    if (!name) { alert("Property name is required."); return; }

    const isObject = !range.startsWith("xsd:");

    try {
      btnAddProp.disabled = true;
      await api("POST", "/api/ontology/change", {
        domain,
        action: "add_property",
        details: {
          name,
          label: label || name,
          domain_class: selectedClassData.name,
          range,
          is_object: isObject,
        },
      });
      document.getElementById("add-prop-name").value = "";
      document.getElementById("add-prop-label").value = "";
      pendingChanges.push({
        action: "add_property", domain,
        details: { class_name: selectedClassData.name, property_name: name },
        timestamp: Date.now(),
      });
      undoStack.push({
        action: "add_property", domain,
        details: { class_name: selectedClassData.name, property_name: name },
        reverseAction: "remove_property",
        reverseDetails: { property_name: name },
      });
      redoStack = [];
      updateDirtyState();
      await reloadCurrentDomain();
    } catch (err) {
      alert("Error adding property: " + err.message);
    } finally {
      btnAddProp.disabled = false;
    }
  }

  async function reloadCurrentDomain() {
    if (!domainSelect.value) return;
    try {
      allDomains = await api("GET", "/api/ontology/query");
      const name = domainSelect.value;
      currentDomain = allDomains.find(d => d.domain === name) || null;
      if (currentDomain) renderGraph(currentDomain);
    } catch (err) {
      console.error("Failed to reload domain:", err);
    }
  }

  // ── Validate ──────────────────────────────────────────────
  async function onValidate() {
    if (!currentDomain) return;
    statusBadge.classList.remove("hidden", "pass", "fail");
    statusBadge.textContent = "Validating…";
    try {
      const result = await api("POST", "/api/validate", { domain: domainSelect.value.replace(".ttl", "") });
      const ok = result.syntax.passed && result.shacl.passed;
      statusBadge.textContent = ok ? "✓ Valid" : "✗ Invalid";
      statusBadge.classList.add(ok ? "pass" : "fail");
    } catch (err) {
      statusBadge.textContent = "✗ Error";
      statusBadge.classList.add("fail");
    }
  }

  // ── Projections modal ────────────────────────────────────
  async function loadProjectTargets() {
    try {
      const data = await api("GET", "/api/project/targets");
      targetCBs.innerHTML = "";
      for (const t of data.targets) {
        const label = document.createElement("label");
        label.innerHTML = `<input type="checkbox" value="${t}" checked> ${t}`;
        targetCBs.appendChild(label);
      }
    } catch (err) {
      targetCBs.textContent = "Failed to load targets";
    }
  }

  async function onRunProject() {
    if (!currentDomain) { modalResult.textContent = "Select a domain first."; return; }
    const checked = [...targetCBs.querySelectorAll("input:checked")].map(i => i.value);
    if (!checked.length) { modalResult.textContent = "Select at least one target."; return; }
    modalResult.innerHTML = "<em>Generating…</em>";
    try {
      const res = await api("POST", "/api/project", {
        domain: domainSelect.value.replace(".ttl", ""),
        targets: checked,
      });
      let html = "";
      for (const [target, files] of Object.entries(res.targets)) {
        html += `<strong>${target}</strong>`;
        for (const [fname, content] of Object.entries(files)) {
          html += `<pre><code>// ${esc(fname)}\n${esc(content)}</code></pre>`;
        }
      }
      modalResult.innerHTML = html;
    } catch (err) {
      modalResult.textContent = "Error: " + err.message;
    }
  }

  // ── Chat ──────────────────────────────────────────────────
  // ── Chat resize ──────────────────────────────────────────
  function initChatResize() {
    const handle = document.getElementById("chat-resize-handle");
    let startX, startW;
    function onMouseMove(e) {
      const delta = startX - e.clientX;
      const newW = Math.min(Math.max(startW + delta, 280), window.innerWidth * 0.6);
      chatPanel.style.width = newW + "px";
    }
    function onMouseUp() {
      handle.classList.remove("dragging");
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    }
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      startX = e.clientX;
      startW = chatPanel.offsetWidth;
      handle.classList.add("dragging");
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  }

  function toggleChat() {
    chatPanel.classList.toggle("hidden");
    if (!chatPanel.classList.contains("hidden")) chatInput.focus();
  }

  function appendChatMsg(role, text, extraClass) {
    const div = document.createElement("div");
    div.className = "chat-msg " + role + (extraClass ? " " + extraClass : "");
    if (role === "user") {
      div.textContent = text;
    } else {
      div.innerHTML = renderMarkdown(text);
    }
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
  }

  function renderMarkdown(md) {
    if (!md) return "";
    const html = marked.parse(md, { breaks: true, gfm: true });
    return DOMPurify.sanitize(html);
  }

  function showToolIndicator(name, intent) {
    // Friendly labels for known tools
    const labels = {
      query_ontology: "Searching ontology",
      propose_change: "Preparing change",
      validate_ontology: "Validating",
      generate_projection: "Generating projection",
      apply_change: "Applying change",
      scaffold_hub: "Scaffolding hub",
      create_domain: "Creating domain",
      explain_ontology: "Analyzing ontology",
      suggest_improvements: "Analyzing for improvements",
      report_intent: intent || "Planning",
      glob: "Searching files",
      grep: "Searching content",
      read_file: "Reading file",
    };
    const label = labels[name] || ("Using " + name);
    let indicator = chatMessages.querySelector(".tool-indicator");
    if (!indicator) {
      indicator = document.createElement("div");
      indicator.className = "tool-indicator";
      chatMessages.appendChild(indicator);
    }
    indicator.innerHTML = '<span class="tool-spinner"></span> ' + esc(label) + "…";
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function hideToolIndicator() {
    const el = chatMessages.querySelector(".tool-indicator");
    if (el) el.remove();
  }

  function showThinkingIndicator() {
    if (chatMessages.querySelector(".thinking-indicator")) return;
    const div = document.createElement("div");
    div.className = "thinking-indicator";
    div.innerHTML = '<span class="tool-spinner"></span> Thinking…';
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function hideThinkingIndicator() {
    const el = chatMessages.querySelector(".thinking-indicator");
    if (el) el.remove();
  }

  async function sendChat() {
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = "";
    btnSend.disabled = true;

    appendChatMsg("user", text);
    chatHistory.push({ role: "user", content: text });

    const assistantDiv = appendChatMsg("assistant", "", "streaming");
    let fullReply = "";

    try {
      const domain = currentDomain ? domainSelect.value.replace(".ttl", "") : undefined;
      const body = { messages: chatHistory };
      if (domain) body.domain = domain;

      const res = await fetch(API + "/api/chat", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(body),
      });

      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE frames
        const lines = buffer.split("\n");
        buffer = lines.pop();  // keep incomplete line
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const raw = line.slice(6);
            let evt;
            try { evt = JSON.parse(raw); } catch (_) { continue; }

            switch (evt.type) {
              case "delta":
                hideThinkingIndicator();
                hideToolIndicator();
                fullReply += evt.content;
                assistantDiv.innerHTML = renderMarkdown(fullReply);
                chatMessages.scrollTop = chatMessages.scrollHeight;
                break;
              case "tool_start":
                showToolIndicator(evt.name, evt.intent);
                break;
              case "tool_end":
                hideToolIndicator();
                break;
              case "thinking":
                showThinkingIndicator();
                break;
              case "error":
                hideThinkingIndicator();
                hideToolIndicator();
                // Show errors inline but styled, not as raw SDK messages
                var errMsg = evt.message || "Unknown error";
                if (errMsg.length > 120) errMsg = errMsg.slice(0, 120) + "…";
                fullReply += '\n\n> ⚠ ' + errMsg + '\n\n';
                assistantDiv.innerHTML = renderMarkdown(fullReply);
                break;
            }
          }
        }
      }

      // Process any remaining buffer
      if (buffer.startsWith("data: ")) {
        try {
          const evt = JSON.parse(buffer.slice(6));
          if (evt.type === "delta") {
            fullReply += evt.content;
            assistantDiv.innerHTML = renderMarkdown(fullReply);
          }
        } catch (_) { /* ignore */ }
      }

      hideThinkingIndicator();
      hideToolIndicator();
      assistantDiv.classList.remove("streaming");
      chatHistory.push({ role: "assistant", content: fullReply });

    } catch (err) {
      hideThinkingIndicator();
      hideToolIndicator();
      assistantDiv.classList.remove("streaming");
      if (!fullReply) {
        assistantDiv.className = "chat-msg error";
        assistantDiv.textContent = "Error: " + err.message;
      }
    }

    btnSend.disabled = false;
    chatInput.focus();
  }

  // ── Utils ─────────────────────────────────────────────────
  function esc(str) {
    const el = document.createElement("span");
    el.textContent = str;
    return el.innerHTML;
  }

  // ── Boot ──────────────────────────────────────────────────
  init();
})();
