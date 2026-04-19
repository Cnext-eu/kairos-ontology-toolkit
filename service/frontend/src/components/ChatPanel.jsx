import { useState, useRef, useEffect, useCallback } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { buildHeaders } from "../api.js";
import { useApp } from "../AppContext.jsx";

const TOOL_LABELS = {
  query_ontology: "Searching ontology",
  propose_change: "Preparing change",
  validate_ontology: "Validating",
  generate_projection: "Generating projection",
  apply_change: "Applying change",
  scaffold_hub: "Scaffolding hub",
  create_domain: "Creating domain",
  explain_ontology: "Analyzing ontology",
  suggest_improvements: "Analyzing for improvements",
  report_intent: "Planning",
  glob: "Searching files",
  grep: "Searching content",
  read_file: "Reading file",
};

function renderMarkdown(md) {
  if (!md) return "";
  const html = marked.parse(md, { breaks: true, gfm: true });
  return DOMPurify.sanitize(html);
}

const ChatPanel = function ChatPanel() {
  const { currentDomain, chatHistory, setChatHistory, setChatOpen, pendingQuickPrompt, setPendingQuickPrompt } = useApp();

  const [messages, setMessages] = useState([]); // {role, text, streaming?, error?}
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [toolLabel, setToolLabel] = useState(null);
  const [thinking, setThinking] = useState(false);
  const [width, setWidth] = useState(380);
  const messagesEndRef = useRef(null);
  const panelRef = useRef(null);

  // Consume pending quick prompt from context
  useEffect(() => {
    if (pendingQuickPrompt) {
      setPendingQuickPrompt(null);
      sendMessage(pendingQuickPrompt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuickPrompt]);

  // Sync messages from chatHistory on mount
  useEffect(() => {
    if (chatHistory.length > 0 && messages.length === 0) {
      setMessages(
        chatHistory.map(m => ({ role: m.role, text: m.content }))
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolLabel, thinking]);

  const sendMessage= useCallback(async (text) => {
    const trimmed = (text || input).trim();
    if (!trimmed || sending) return;
    setInput("");
    setSending(true);

    const userMsg = { role: "user", text: trimmed };
    setMessages(prev => [...prev, userMsg]);

    const history = [...chatHistory, { role: "user", content: trimmed }];
    setChatHistory(history);

    const assistantIdx = messages.length + 1;
    setMessages(prev => [...prev, { role: "assistant", text: "", streaming: true }]);

    let fullReply = "";

    try {
      const domain = currentDomain ? currentDomain.domain.replace(".ttl", "") : undefined;
      const body = { messages: history };
      if (domain) body.domain = domain;

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(body),
        credentials: "same-origin",
      });

      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let evt;
          try { evt = JSON.parse(line.slice(6)); } catch (_) { continue; }

          switch (evt.type) {
            case "delta":
              setThinking(false);
              setToolLabel(null);
              fullReply += evt.content;
              setMessages(prev => prev.map((m, i) =>
                i === prev.length - 1 ? { ...m, text: fullReply } : m
              ));
              break;
            case "tool_start":
              setToolLabel(TOOL_LABELS[evt.name] || `Using ${evt.name}`);
              break;
            case "tool_end":
              setToolLabel(null);
              break;
            case "thinking":
              setThinking(true);
              break;
            case "error": {
              setThinking(false);
              setToolLabel(null);
              let errMsg = evt.message || "Unknown error";
              if (errMsg.length > 120) errMsg = errMsg.slice(0, 120) + "…";
              fullReply += `\n\n> ⚠ ${errMsg}\n\n`;
              setMessages(prev => prev.map((m, i) =>
                i === prev.length - 1 ? { ...m, text: fullReply } : m
              ));
              break;
            }
          }
        }
      }

      setMessages(prev => prev.map((m, i) =>
        i === prev.length - 1 ? { ...m, streaming: false } : m
      ));
      setChatHistory(h => [...h, { role: "assistant", content: fullReply }]);
    } catch (err) {
      setMessages(prev => prev.map((m, i) =>
        i === prev.length - 1
          ? { role: "assistant", text: fullReply || `Error: ${err.message}`, error: !fullReply, streaming: false }
          : m
      ));
    } finally {
      setThinking(false);
      setToolLabel(null);
      setSending(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, sending, currentDomain, chatHistory, messages.length]);

  // ── Resize handle ─────────────────────────────────────────
  function onResizeMouseDown(e) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = panelRef.current?.offsetWidth || width;
    function onMove(ev) {
      const newW = Math.min(Math.max(startW + (startX - ev.clientX), 280), window.innerWidth * 0.6);
      setWidth(newW);
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  return (
    <div id="chat-panel" ref={panelRef} style={{ width }}>
      <div id="chat-resize-handle" onMouseDown={onResizeMouseDown} />
      <div id="chat-header">
        <span>Ontology Assistant</span>
        <button className="close-btn" onClick={() => setChatOpen(false)}>✕</button>
      </div>

      <div id="chat-messages">
        {messages.map((m, i) => (
          <div
            key={i}
            className={[
              "chat-msg",
              m.role,
              m.streaming ? "streaming" : "",
              m.error ? "error" : "",
            ].filter(Boolean).join(" ")}
            {...(m.role === "assistant"
              ? { dangerouslySetInnerHTML: { __html: renderMarkdown(m.text) } }
              : { children: m.text }
            )}
          />
        ))}
        {thinking && (
          <div className="thinking-indicator">
            <span className="tool-spinner" /> Thinking…
          </div>
        )}
        {toolLabel && (
          <div className="tool-indicator">
            <span className="tool-spinner" /> {toolLabel}…
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div id="chat-input-area">
        <textarea
          id="chat-input"
          placeholder="Ask about the ontology…"
          rows="2"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
          }}
        />
        <button id="btn-send" onClick={() => sendMessage()} disabled={sending || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
};

export default ChatPanel;
