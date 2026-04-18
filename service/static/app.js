/* Kairos Ontology Hub — main application logic */
(function () {
  "use strict";

  const API = "";  // same origin
  let AUTH = "Bearer dev-token";  // default; replaced by /api/config in dev mode

  // ── DOM refs ──────────────────────────────────────────────
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

  // ── State ─────────────────────────────────────────────────
  let cy = null;
  let allDomains = [];       // [{domain, namespace, classes, relationships}]
  let currentDomain = null;
  let chatHistory = [];      // [{role, content}]

  // ── Helpers ───────────────────────────────────────────────
  function headers(extra) {
    return Object.assign({ "Authorization": AUTH, "Content-Type": "application/json" }, extra || {});
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
    } catch (_) { /* non-critical */ }

    initGraph();
    await loadDomains();
    loadProjectTargets();
    domainSelect.addEventListener("change", onDomainChange);
    searchInput.addEventListener("input", onSearch);
    btnValidate.addEventListener("click", onValidate);
    btnProject.addEventListener("click", () => modalOverlay.classList.remove("hidden"));
    btnToggleChat.addEventListener("click", toggleChat);
    btnCloseChat.addEventListener("click", toggleChat);
    btnCloseDetail.addEventListener("click", () => detailPanel.classList.add("hidden"));
    btnCloseModal.addEventListener("click", () => modalOverlay.classList.add("hidden"));
    btnRunProject.addEventListener("click", onRunProject);
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
      ],
      layout: { name: "grid" },
      minZoom: 0.3,
      maxZoom: 3,
    });
    cy.on("tap", "node", (e) => showDetail(e.target.data()));
    cy.on("tap", (e) => { if (e.target === cy) detailPanel.classList.add("hidden"); });
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

    detailPanel.classList.remove("hidden");
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
