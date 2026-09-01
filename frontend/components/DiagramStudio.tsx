"use client";

import { useEffect, useRef, useState } from "react";

const MERMAID_SAMPLE = `flowchart TD
  task[User task] --> agent[Olladex agent]
  agent --> tools{Choose tool}
  tools --> files[Repository]
  tools --> bash[Bash]
  tools --> office[Office]`;

const DOT_SAMPLE = `digraph Olladex {
  rankdir=LR;
  node [shape=box, style="rounded,filled", fillcolor="#eaf2ff", color="#1768e5"];
  User -> Agent;
  Agent -> Repository;
  Agent -> Bash;
  Agent -> Ollama;
}`;

export function DiagramStudio({ initialSource, initialEngine }: { initialSource?: string; initialEngine?: "mermaid" | "dot" }) {
  const [engine, setEngine] = useState<"mermaid" | "dot">(initialEngine || "mermaid");
  const [source, setSource] = useState(initialSource || MERMAID_SAMPLE);
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const id = useRef(0);

  useEffect(() => {
    if (initialSource) setSource(initialSource);
    if (initialEngine) setEngine(initialEngine);
  }, [initialSource, initialEngine]);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        setError("");
        if (engine === "mermaid") {
          const mermaid = (await import("mermaid")).default;
          mermaid.initialize({ startOnLoad: false, theme: "base", securityLevel: "strict", themeVariables: { primaryColor: "#eaf2ff", primaryBorderColor: "#1768e5", primaryTextColor: "#15233a", lineColor: "#64748b" } });
          const rendered = await mermaid.render(`olladex-diagram-${++id.current}`, source);
          if (!cancelled) setSvg(rendered.svg);
        } else {
          const { instance } = await import("@viz-js/viz");
          const viz = await instance();
          const rendered = viz.renderSVGElement(source);
          if (!cancelled) setSvg(rendered.outerHTML);
        }
      } catch (err) {
        if (!cancelled) { setSvg(""); setError(err instanceof Error ? err.message : String(err)); }
      }
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [source, engine]);

  function changeEngine(next: "mermaid" | "dot") {
    setEngine(next);
    setSource(next === "mermaid" ? MERMAID_SAMPLE : DOT_SAMPLE);
  }

  function download() {
    const blob = new Blob([svg], { type: "image/svg+xml" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `olladex-${engine}.svg`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return <div className="diagram-studio">
    <div className="diagram-toolbar">
      <div className="segmented"><button className={engine === "mermaid" ? "active" : ""} onClick={() => changeEngine("mermaid")}>Mermaid</button><button className={engine === "dot" ? "active" : ""} onClick={() => changeEngine("dot")}>Graphviz / DOT</button></div>
      <button onClick={download} disabled={!svg}>↓ Export SVG</button>
    </div>
    <div className="diagram-grid">
      <textarea aria-label="Diagram source" value={source} onChange={(e) => setSource(e.target.value)} spellCheck={false} />
      <div className="diagram-preview">{error ? <div className="error-card"><strong>Diagram error</strong><p>{error}</p></div> : <div className="svg-canvas" dangerouslySetInnerHTML={{ __html: svg }} />}</div>
    </div>
  </div>;
}

