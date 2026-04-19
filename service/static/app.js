/* Kairos Ontology Hub — main application logic */
(function () {
  "use strict";

  const API = "";  // same origin
  let AUTH = "Bearer dev-token";  // default; replaced by /api/config in dev mode

  // ── DOM refs ──────────────────────────────────────────────
  const repoSelect     = document.getElementById("repo-select");
  const domainSelect   = document.getElementById("domain-select");
  const searchInput    = document.getElementById("search-input");
  const btnValidate    = document.getElementById("btn-validate");
  const btnProject     = document.getElementById("btn-project");
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
  const btnAddClass       = document.getElementById("btn-add-class");
  const addClassOverlay   = document.getElementById("add-class-overlay");
  const btnCloseAddClass  = document.getElementById("btn-close-add-class");
  const btnCreateClass    = document.getElementById("btn-create-class");
  const btnCancelAddClass = document.getElementById("btn-cancel-add-class");
  const contextMenu       = document.getElementById("context-menu");
  const ctxEdit           = document.getElementById("ctx-edit");
  const ctxAddProp        = document.getElementById("ctx-add-prop");
  const ctxAddSub         = document.getElementById("ctx-add-sub");
  const ctxDelete         = document.getElementById("ctx-delete");

  // ── State ─────────────────────────────────────────────────
  let cy = null;
  let allDomains = [];       // [{domain, namespace, classes, relationships}]
  let currentDomain = null;
  let chatHistory = [];      // [{role, content}]
  let activeRepo = null;     // {owner, name, full_name, default_branch}
  let selectedClassData = null;
  let pendingChanges = [];   // [{action, domain, details, timestamp}]

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
    btnValidate.addEventListener("click", onValidate);
    btnProject.addEventListener("click", () => modalOverlay.classList.remove("hidden"));
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
    btnAddClass.addEventListener("click", showAddClassDialog);
    btnCloseAddClass.addEventListener("click", hideAddClassDialog);
    btnCreateClass.addEventListener("click", onCreateClass);
    btnCancelAddClass.addEventListener("click", hideAddClassDialog);
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
      hideAddClassDialog();
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
  }

  function onRepoChange() {
    const val = repoSelect.value;
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
      exitEditMode();
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
    try {
      await api("POST", "/api/ontology/change", {
        domain,
        action: "remove_class",
        details: { class_name: selectedClassData.name },
      });
      pendingChanges.push({
        action: "remove_class", domain,
        details: { class_name: selectedClassData.name },
        timestamp: Date.now(),
      });
      detailPanel.classList.add("hidden");
      selectedClassData = null;
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
        details: { class_name: selectedClassData.name },
        timestamp: Date.now(),
      });
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
