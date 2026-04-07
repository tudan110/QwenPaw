import { useEffect, useId, useState } from "react";
import mermaid from "mermaid";

interface MermaidBlockProps {
  chart: string;
}

let mermaidInitialized = false;

function ensureMermaidInitialized() {
  if (mermaidInitialized) {
    return;
  }
  mermaid.initialize({
    startOnLoad: false,
    theme: "default",
    securityLevel: "loose",
    fontFamily: "Inter, Noto Sans SC, sans-serif",
  });
  mermaidInitialized = true;
}

export function MermaidBlock({ chart }: MermaidBlockProps) {
  const id = useId().replace(/:/g, "-");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const source = String(chart || "").trim();
    if (!source) {
      setSvg("");
      setError("");
      return;
    }

    let cancelled = false;
    ensureMermaidInitialized();
    mermaid
      .render(`mermaid-${id}`, source)
      .then((result) => {
        if (cancelled) {
          return;
        }
        setSvg(result.svg);
        setError("");
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        console.error("Failed to render Mermaid chart:", err);
        setSvg("");
        setError("拓扑图配置解析失败");
      });

    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  if (error) {
    return (
      <pre
        style={{
          padding: 16,
          background: "#fff1f0",
          border: "1px solid #ffa39e",
          borderRadius: 6,
          overflow: "auto",
        }}
      >
        <code>{chart}</code>
      </pre>
    );
  }

  if (!svg) {
    return (
      <div
        style={{
          minHeight: 220,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background:
            "linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%)",
          borderRadius: 16,
          padding: 16,
          border: "1px solid rgba(148, 163, 184, 0.18)",
          color: "#64748b",
        }}
      >
        正在生成拓扑图...
      </div>
    );
  }

  return (
    <div
      style={{
        width: "100%",
        overflow: "auto",
        background:
          "linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%)",
        borderRadius: 16,
        padding: 12,
        border: "1px solid rgba(148, 163, 184, 0.18)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(15, 23, 42, 0.05)",
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
