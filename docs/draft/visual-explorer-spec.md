# Kairos Ontology Hub — Visual Explorer (Specification Plan)

## Problem Statement

Business analysts need a browser-based interactive tool to explore ontology hubs
without reading TTL files. The tool should let them understand domain models,
trace data lineage from source systems through silver/gold layers, see mapping
coverage, and ask natural-language questions — all through an intuitive web UI.

## Proposed Approach

Build an **AG-UI powered web application** that:
- Uses the existing FastAPI service as the backend (already has ontology parsing,
  projection, and chat endpoints)
- Adds a modern frontend (React + CopilotKit for AG-UI streaming)
- Leverages the existing A2UI projection schemas for adaptive UI rendering
- Is read-only for v1, but architecturally extensible for future editing

---

## What Business Analysts & Data Engineers Expect

### Business Analyst Expectations

| Expectation | Why it matters |
|---|---|
| **No-code exploration** | BAs won't read TTL/SPARQL — they need click-to-explore navigation |
| **Business language** | Show `rdfs:label` and `rdfs:comment`, not URIs or technical names |
| **Lineage visualization** | "Where does this field come from?" — trace source → silver → gold |
| **Coverage dashboards** | "How much of source system X is mapped?" — percentage bars, unmapped lists |
| **Search by concept** | Find classes/properties by keyword, not by knowing the namespace |
| **Domain-first navigation** | Organized by business domain (Client, Invoice), not by file structure |
| **Export-friendly** | Copy tables to Excel, export diagrams as PNG/SVG for presentations |
| **Relationship diagrams** | Visual graphs showing class relationships (like an ERD but richer) |
| **Gap identification** | Clearly highlight unmapped source fields and missing transformations |
| **Natural language Q&A** | "What entities relate to Customer?" without knowing SPARQL |

### Data Engineer Expectations (future consideration)

| Expectation | Why it matters |
|---|---|
| **Schema inspection** | View generated DDL, dbt models, column types before deployment |
| **Validation status** | See SHACL violations, syntax errors, annotation completeness |
| **Projection diff** | "What changed in silver output since last commit?" |
| **Annotation completeness** | Which classes are missing `kairos-ext:` annotations for silver/gold? |
| **Cross-domain dependencies** | Imported reference models, shared properties |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Frontend — NEW: explorer/frontend/                     │
│  (React + TypeScript + Vite, standalone app)            │
│  ┌────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐  │
│  │Cytoscape.js│ │React Flow│ │Recharts │ │ AI Chat  │  │
│  │(ontology   │ │(lineage  │ │(coverage│ │ (AG-UI   │  │
│  │ graph)     │ │ diagrams)│ │ stats)  │ │  SSE)    │  │
│  └────────────┘ └──────────┘ └─────────┘ └──────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP REST + AG-UI (SSE streaming)
┌───────────────────────┴─────────────────────────────────┐
│  Backend — NEW: explorer/backend/                       │
│  (FastAPI, standalone service, own dependencies)        │
│  ┌──────────────┐ ┌────────────┐ ┌───────────────────┐  │
│  │Explorer API  │ │Ontology    │ │AG-UI SSE Chat     │  │
│  │(graph, stats,│ │Parser      │ │(GitHub Models API)│  │
│  │ lineage)     │ │(rdflib)    │ │                   │  │
│  └──────────────┘ └────────────┘ └───────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ reads TTL files from disk
┌───────────────────────┴─────────────────────────────────┐
│  Ontology Hub (TTL files — pointed to via config)       │
│  model/ · sources/ · output/ · shapes/                  │
└─────────────────────────────────────────────────────────┘
```

### Folder Structure

```
C:\code\kairos-ontology-toolkit\
└── explorer/                      ← NEW top-level folder
    ├── README.md
    ├── backend/
    │   ├── pyproject.toml         ← own Poetry project (not shared with toolkit)
    │   ├── app/
    │   │   ├── __init__.py
    │   │   ├── main.py            ← FastAPI app entry
    │   │   ├── config.py          ← hub path, LLM config
    │   │   ├── routers/
    │   │   │   ├── explorer.py    ← /api/domains, /api/classes, /api/graph, etc.
    │   │   │   ├── lineage.py     ← /api/lineage
    │   │   │   ├── coverage.py    ← /api/coverage
    │   │   │   └── chat.py        ← /api/chat (AG-UI SSE)
    │   │   ├── services/
    │   │   │   ├── ontology_parser.py  ← rdflib graph loading (fresh code)
    │   │   │   ├── lineage_service.py  ← source→silver→gold tracing
    │   │   │   └── chat_service.py     ← GitHub Models API + AG-UI events
    │   │   └── models/            ← Pydantic response schemas
    │   └── tests/
    └── frontend/
        ├── package.json           ← own npm project
        ├── vite.config.ts
        ├── tailwind.config.ts
        ├── tsconfig.json
        ├── src/
        │   ├── App.tsx
        │   ├── main.tsx
        │   ├── hooks/
        │   │   ├── useAgentChat.ts    ← AG-UI SSE consumer (text chat fallback)
        │   │   └── useVoiceLive.ts    ← Voice Live WebSocket hook (audio + function calls)
        │   ├── pages/
        │   │   ├── DomainsPage.tsx
        │   │   ├── ClassExplorerPage.tsx
        │   │   ├── LineagePage.tsx
        │   │   └── CoveragePage.tsx
        │   ├── components/
        │   │   ├── OntologyGraph.tsx  ← Cytoscape.js wrapper
        │   │   ├── LineageFlow.tsx    ← React Flow wrapper
        │   │   ├── ChatPanel.tsx      ← AG-UI streaming chat + voice controls
        │   │   ├── VoiceButton.tsx    ← mic toggle + visual feedback
        │   │   └── CoverageChart.tsx
        │   └── lib/
        │       ├── api.ts            ← fetch helpers
        │       └── graph-actions.ts  ← canvas navigation (focus, highlight, zoom)
        └── public/
```

## Key Design Decisions

1. **Standalone app in `explorer/`** — Completely separate from the existing
   toolkit `src/` and `service/`. Own Poetry project (backend), own npm project
   (frontend). Does NOT import or reuse existing toolkit code — fresh
   implementation that reads TTL files directly with rdflib.

2. **Native AG-UI for AI chat** — Implement the AG-UI protocol directly on the
   backend (FastAPI SSE endpoint). Frontend consumes with a thin custom hook.
   No CopilotKit dependency. Consistent with our own-the-protocol philosophy.

3. **A2UI schemas as future extension** — The explorer is independent, but can
   later consume A2UI JSON Schemas (generated by the toolkit) to render adaptive
   edit forms when editing is enabled.

4. **Cytoscape.js for ontology graph + React Flow for lineage** — Hybrid
   approach: Cytoscape.js handles large, complex class hierarchies; React Flow
   handles small, linear lineage DAGs.

5. **Hub-agnostic** — The explorer backend takes a hub path as config and reads
   TTL files from disk. Works with any ontology hub regardless of whether it
   was created by the toolkit.

---

## Implementation Phases

### Phase 1 — Backend API (Standalone)

- New FastAPI app: `explorer/backend/app/main.py`
- Own `pyproject.toml` with dependencies: `fastapi`, `uvicorn`, `rdflib`, `pydantic`
- Routers:
  - `GET /api/domains` — list ontology domains with stats
  - `GET /api/domains/{domain}/classes` — classes with labels, comments
  - `GET /api/domains/{domain}/graph` — nodes + edges for Cytoscape.js
  - `GET /api/lineage/{domain}` — source→silver→gold trace
  - `GET /api/coverage` — mapping coverage statistics
  - `GET /api/search?q=...` — full-text concept search
  - `GET /api/chat` — AG-UI SSE streaming endpoint (with `visualize` tool)
- The chat endpoint exposes a `visualize` tool to the LLM. When the AI detects
  a concept-related question, it calls `visualize(concept_uri)` which emits an
  AG-UI `ToolCallEnd` event. The frontend interprets this to navigate the canvas.
- Fresh rdflib-based ontology parser (does NOT import from `kairos_ontology`)
- Config: points to an ontology hub directory on disk

### Phase 2 — Frontend Shell (Standalone)

- React + TypeScript app in `explorer/frontend/` (Vite bundler)
- Own `package.json` — no shared dependencies with toolkit
- No CopilotKit — plain React with custom AG-UI hook
- Tailwind CSS for styling
- Pages: Domain list → Class explorer → Lineage view → Coverage dashboard
- Responsive layout suitable for analysts on laptops/tablets

### Phase 3 — Visualization Components

- **Cytoscape.js** for interactive ontology class/relationship graph
  (hierarchical layout, expand/collapse, search-highlight, CSS-like styling)
- **React Flow** for lineage flow diagrams (source tables → silver → gold)
- **Recharts** for coverage heatmap and statistics (per-source, per-domain)
- Mapping detail panels (SKOS match type, transforms, filters)

### Phase 4 — AI Chat Integration (Native AG-UI) + Voice Live

- New FastAPI SSE endpoint implementing AG-UI event protocol directly
- Wraps GitHub Models API as the LLM backend (fresh implementation)
- Emits standard AG-UI events: `TextMessageStart`, `TextMessageContent`,
  `TextMessageEnd`, `ToolCallStart`, `ToolCallEnd`, etc.
- Frontend: thin custom React hook (`useAgentChat`) consuming the SSE stream
- Context-aware: system prompt includes ontology graph summary
- Example questions: "What properties does Customer have?",
  "Show me unmapped fields in the CRM source", "Explain the Invoice domain"

#### Voice Interaction — Azure Voice Live API (Speech-to-Speech)

Instead of separate STT + TTS SDKs, we use **Azure Voice Live API** — a unified
speech-to-speech solution that handles everything in one WebSocket connection:
audio in → AI reasoning → audio out, with minimal latency.

**Why Voice Live instead of separate STT/TTS:**
- Single WebSocket connection (no manual orchestration of STT → LLM → TTS)
- Built-in echo cancellation, noise suppression, interruption detection
- End-to-end low latency (no chaining delay)
- Function calling support (the AI can trigger `visualize` actions mid-conversation)
- Choice of backing models (GPT-4.1, GPT-5, gpt-realtime, Phi-4)
- Fully managed — no model deployment needed

**Architecture:**

```
┌────────────────────────────────────────────────────────────┐
│  Browser (frontend)                                        │
│  ┌─────────┐                          ┌──────────────────┐ │
│  │ Mic →   │  audio stream            │ Speaker ←        │ │
│  │ WebRTC/ │─────────┐   ┌───────────▶│ Web Audio API    │ │
│  │ MediaAPI│         │   │            └──────────────────┘ │
│  └─────────┘         │   │                                 │
│                      ▼   │  audio + function_call events    │
│              ┌────────────────────┐                         │
│              │  Voice Live Hook   │──── visualize action ──▶│
│              │  (WebSocket client)│                         │
│              └─────────┬──────────┘          ┌───────────┐ │
│                        │                     │Cytoscape.js│ │
│                        │ text transcript     │  Canvas    │ │
│                        ▼                     └───────────┘ │
│              ┌──────────────┐                              │
│              │ Chat Panel   │ (shows text alongside voice) │
│              └──────────────┘                              │
└────────────────────────┬───────────────────────────────────┘
                         │ WebSocket (audio + events)
┌────────────────────────┴───────────────────────────────────┐
│  Explorer Backend (proxy/relay)                            │
│  WebSocket endpoint that:                                  │
│  1. Connects to Azure Voice Live API                       │
│  2. Injects system prompt (ontology context)               │
│  3. Registers `visualize` function for graph navigation    │
│  4. Relays audio bidirectionally                           │
└────────────────────────┬───────────────────────────────────┘
                         │ WebSocket (Azure OpenAI Realtime-compatible)
┌────────────────────────┴───────────────────────────────────┐
│  Azure Voice Live API (fully managed)                      │
│  - Speech recognition (140+ locales)                       │
│  - LLM reasoning (GPT-4.1 / GPT-5 / gpt-realtime)        │
│  - Speech synthesis (600+ neural voices)                   │
│  - Function calling → triggers `visualize(concept_uri)`    │
│  - Echo cancellation + noise suppression                   │
│  - Advanced end-of-turn detection                          │
└────────────────────────────────────────────────────────────┘
```

**Voice Live configuration:**
- Model: `gpt-4.1` (good balance of intelligence + cost) or `gpt-realtime` for
  lowest latency
- Voice: Standard Azure neural voice (e.g., `en-US-JennyNeural`)
- System prompt: includes ontology domain summary + available tools
- Tools registered:
  - `visualize(concept_uri, action)` — navigate canvas to a concept
  - `search(query)` — search ontology and present results
  - `show_lineage(entity)` — switch to lineage view for an entity

**Canvas navigation from voice:**
When the AI identifies an ontology concept in the user's question, it calls the
`visualize` function. The backend relays this as a function_call event to the
frontend, which:
1. Pans/zooms the Cytoscape.js canvas to the target concept
2. Highlights the node with a pulse animation
3. Optionally expands the neighborhood (related classes/properties)
4. The AI continues speaking its explanation while the visual updates happen

**Voice + Visual Flow Example:**

```
User (speaks): "What is the relationship between Customer and Invoice?"

Azure Voice Live (simultaneous):
  → Audio response: "Customer has a one-to-many relationship with Invoice
     through the 'hasInvoice' property. Let me show you on the graph."
  → Function call: visualize({ concept: "Customer", related: ["Invoice"],
     highlight_edge: "hasInvoice" })

Frontend (simultaneous):
  → Plays audio through speaker
  → Shows transcript in chat panel
  → Zooms canvas to Customer, highlights edge to Invoice
```

### Phase 5 — Polish & Extensibility Hooks

- Export: SVG/PNG for diagrams, CSV for coverage reports
- Deep linking (share a URL pointing to a specific class or mapping)
- Extension points for future editing (annotation suggestions, gap flagging)
- CI integration: generate static explorer as part of `kairos-ontology project`

---

## Technology Choices (Recommended)

| Layer | Technology | Rationale |
|---|---|---|
| Frontend framework | React 18+ with TypeScript | Widely known, strong ecosystem |
| AI interaction | **Native AG-UI protocol** (direct implementation) | Aligns with the existing A2UI projector philosophy — our own protocol-compliant endpoint, no third-party SDK dependency. See rationale below. |
| Graph visualization | **Cytoscape.js** (embedded in React) | Best for ontologies — handles large graphs (1000+ nodes), has built-in graph algorithms (BFS, shortest-path), hierarchical/force-directed layouts, and CSS-like styling. See comparison below. |
| Lineage diagrams | **React Flow** (dagre layout) | Directed left-to-right flow diagrams (source→silver→gold). React Flow excels at small, editor-like DAG visualizations. |
| Voice (STT + TTS) | **Azure Voice Live API** | Unified speech-to-speech: single WebSocket for audio in→AI→audio out; built-in echo cancellation, noise suppression, function calling |
| Voice model | `gpt-4.1` or `gpt-realtime` via Voice Live | Managed model, no deployment needed; supports tool calling for `visualize` actions |
| Charts/stats | Recharts or Chart.js | Lightweight, responsive |
| Styling | Tailwind CSS | Rapid prototyping, consistent with modern tools |
| Backend | FastAPI (standalone) | Clean separation, own project |
| Data fetching | `fetch` + React context (or SWR if needed) | Simple; no heavy library needed for a read-only explorer. See note below. |

### Why Native AG-UI Instead of CopilotKit?

CopilotKit is a third-party React SDK that *implements* the AG-UI protocol with
opinionated hooks (`useAgent`, `useCopilotChat`) and pre-built UI components.
It's convenient but adds:
- A vendor dependency (npm package, versioning, breaking changes)
- Assumptions about UI layout (chat panel styling, popup placement)
- License considerations (CopilotKit is source-available, not Apache 2.0)

**Our approach:** Implement the AG-UI protocol directly on the backend (FastAPI
SSE endpoint emitting AG-UI events) and consume it in the frontend with a thin
custom hook. This is consistent with how the existing **A2UI projector** works —
we define JSON Schemas from the ontology and render them ourselves, rather than
depending on a third-party form library.

Benefits:
- Full control over UX (chat panel, streaming display, tool-call rendering)
- No third-party SDK license risk for our Apache 2.0 project
- Lighter bundle, fewer dependencies
- The AG-UI event format is simple (JSON over SSE) — a custom hook is ~50 lines

### Why Cytoscape.js for the Ontology Graph (Not React Flow)?

| Criterion | Cytoscape.js | React Flow |
|---|---|---|
| **Scale** | Handles 5000+ nodes smoothly (canvas/WebGL) | Struggles above ~500 nodes (DOM-based) |
| **Built-in layouts** | 10+ including hierarchical, CoSE, concentric | Needs external lib (dagre/elk) for every layout |
| **Graph algorithms** | BFS, DFS, Dijkstra, PageRank, betweenness centrality | None |
| **Ontology fit** | Designed for biology/knowledge graphs; compound nodes for class hierarchies | Designed for workflow editors and DAGs |
| **Custom styling** | CSS-like stylesheet (selectors, classes, states) | React components per node |
| **Framework** | Framework-agnostic (React wrapper available) | React-only |

**Verdict:** Use **Cytoscape.js** for the main ontology class/relationship graph
(which can be large and deeply hierarchical). Use **React Flow** only for the
lineage diagrams (small, linear DAGs where drag-and-drop layout is nice).

### Why No TanStack Query?

TanStack Query (formerly React Query) is a data-fetching + caching library for
React. It's excellent for apps with many independent, frequently-updating server
queries (e.g., dashboards with real-time data, paginated lists with optimistic
updates). It provides:
- Automatic caching, refetching on focus/reconnect
- Loading/error state management
- Background refresh and stale-while-revalidate

**For our use case** (read-only explorer, ontology data that changes rarely, no
real-time updates), it's overkill. A simple `useEffect` + `fetch` pattern or the
lightweight `useSWR` hook is sufficient. If the app grows in complexity later
(editing, real-time collaboration), TanStack Query can be added then.

**Decision:** Start simple — plain `fetch` + React state. Add SWR or TanStack
Query only if caching/deduplication becomes a problem.

---

## Risks & Considerations

- **Performance with large ontologies** — Lazy-load graph data; paginate class
  lists; consider WebSocket for large graph streaming
- **Hub discovery** — Backend needs a config path to the hub; consider supporting
  multiple hubs or a hub selector in the UI
- **No shared code with toolkit** — Deliberate isolation; if ontology parsing
  conventions change in the toolkit, the explorer's parser must be updated
  independently (trade-off: independence vs. potential drift)
- **Auth** — Start without auth (local dev tool); add JWT or API key later if
  deployed as a shared team service
- **Offline/CI mode** — Consider a CLI command that generates a self-contained
  HTML bundle for offline viewing (future phase)

---

## Notes

- The existing **mapping report** (`report` projection target) already generates
  per-source-system HTML with coverage stats and lineage. The visual explorer
  is its interactive, richer successor.
- The existing **A2UI projector** generates JSON Schemas from ontology classes —
  these schemas define message types that could power adaptive UI panels.
- The existing **prompt projector** generates structured ontology context for LLMs,
  which the AI chat can use as system context.
