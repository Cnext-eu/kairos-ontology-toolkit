import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import { useApp } from "../AppContext.jsx";

const CY_STYLE = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "background-color": "#1f6feb",
      color: "#c9d1d9",
      "text-valign": "bottom",
      "text-margin-y": 6,
      "font-size": 12,
      width: 40,
      height: 40,
      "border-width": 2,
      "border-color": "#58a6ff",
    },
  },
  {
    selector: "node.has-super",
    style: { "background-color": "#238636", "border-color": "#3fb950" },
  },
  {
    selector: "node:selected",
    style: { "border-color": "#f0883e", "border-width": 3 },
  },
  {
    selector: "edge",
    style: {
      width: 2,
      "line-color": "#30363d",
      "target-arrow-color": "#30363d",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      label: "data(label)",
      "font-size": 10,
      color: "#484f58",
      "text-rotation": "autorotate",
      "text-margin-y": -8,
    },
  },
  {
    selector: "edge.inheritance",
    style: {
      "line-color": "#3fb950",
      "line-style": "dashed",
      "target-arrow-color": "#3fb950",
      "target-arrow-shape": "triangle",
    },
  },
  {
    selector: "node.modified",
    style: { "border-color": "#d29922", "border-width": 3, "border-style": "dashed" },
  },
  {
    selector: "node.new-node",
    style: { "border-color": "#3fb950", "border-width": 3, "border-style": "dashed" },
  },
];

export default function GraphPanel() {
  const {
    currentDomain,
    pendingChanges,
    setSelectedClass,
    setDetailOpen,
    setContextMenu,
    setAddClassOpen,
    setAddClassPreSuper,
  } = useApp();

  const containerRef = useRef(null);
  const cyRef = useRef(null);

  // ── Init Cytoscape once ───────────────────────────────────
  useEffect(() => {
    cyRef.current = cytoscape({
      container: containerRef.current,
      style: CY_STYLE,
      layout: { name: "grid" },
      minZoom: 0.3,
      maxZoom: 3,
    });

    const cy = cyRef.current;

    cy.on("tap", "node", e => {
      setSelectedClass(e.target.data());
      setDetailOpen(true);
    });

    cy.on("tap", e => {
      if (e.target === cy) {
        setDetailOpen(false);
        setContextMenu(null);
      }
    });

    cy.on("dbltap", e => {
      if (e.target === cy) {
        setAddClassPreSuper("");
        setAddClassOpen(true);
      }
    });

    cy.on("cxttap", "node", e => {
      e.originalEvent.preventDefault();
      const x = e.originalEvent.clientX;
      const y = e.originalEvent.clientY;
      setContextMenu({ x, y, classData: e.target.data() });
      setSelectedClass(e.target.data());
    });

    document.addEventListener("click", () => setContextMenu(null));

    // Expose search callback for Sidebar
    window.__kairosSearch = term => {
      cy.nodes().forEach(n => {
        const match = !term
          || n.data("label").toLowerCase().includes(term.toLowerCase())
          || (n.data("comment") || "").toLowerCase().includes(term.toLowerCase());
        n.style("opacity", match ? 1 : 0.15);
      });
    };

    return () => {
      cy.destroy();
      delete window.__kairosSearch;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Re-render graph when domain or pending changes update ──
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().remove();

    if (!currentDomain) return;

    const elements = [];

    for (const cls of currentDomain.classes) {
      elements.push({
        group: "nodes",
        data: { id: cls.uri, label: cls.name, ...cls },
        classes: cls.superclasses?.length > 0 ? "has-super" : "",
      });
    }

    for (const cls of currentDomain.classes) {
      if (cls.superclasses) {
        for (const sup of cls.superclasses) {
          const parent = currentDomain.classes.find(c => c.name === sup);
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

    if (currentDomain.relationships) {
      for (const rel of currentDomain.relationships) {
        const src = currentDomain.classes.find(c => c.name === rel.domain || c.uri === rel.domain);
        const tgt = currentDomain.classes.find(c => c.name === rel.range || c.uri === rel.range);
        if (src && tgt) {
          elements.push({
            group: "edges",
            data: { source: src.uri, target: tgt.uri, label: rel.name },
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

    // Highlight pending changes
    for (const change of pendingChanges) {
      const name = change.details?.class_name || change.details?.name;
      if (!name) continue;
      const node = cy.nodes().filter(n => n.data("name") === name);
      node.addClass(change.action === "add_class" ? "new-node" : "modified");
    }
  }, [currentDomain, pendingChanges]);

  const showEmpty = !currentDomain;

  return (
    <div id="graph-container">
      <div id="cy" ref={containerRef} />
      {showEmpty && (
        <div id="graph-empty">Select a domain to visualize</div>
      )}
    </div>
  );
}
