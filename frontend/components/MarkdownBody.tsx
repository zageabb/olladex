"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Props = {
  value: string;
  compact?: boolean;
  className?: string;
};

function normaliseMarkdown(value: string) {
  return String(value || "").replace(/<br\s*\/?>/gi, "  \n");
}

export function MarkdownBody({ value, compact = false, className = "" }: Props) {
  return (
    <div className={`markdown-body${compact ? " markdown-compact" : ""}${className ? ` ${className}` : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const external = Boolean(href && /^(https?:)?\/\//i.test(href));
            return (
              <a href={href} target={external ? "_blank" : undefined} rel={external ? "noopener noreferrer" : undefined}>
                {children}
              </a>
            );
          },
          table: ({ children }) => (
            <div className="markdown-table-wrap">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {normaliseMarkdown(value)}
      </ReactMarkdown>
    </div>
  );
}
