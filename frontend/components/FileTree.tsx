"use client";

export type TreeNode = { name: string; path: string; type: "file" | "directory"; size?: number; children?: TreeNode[] };

export function FileTree({ items, selected, onSelect, level = 0 }: { items: TreeNode[]; selected?: string; onSelect: (item: TreeNode) => void; level?: number }) {
  return <>{items.map((item) => <div key={item.path}>
    <button
      className={`tree-row ${selected === item.path ? "selected" : ""}`}
      style={{ paddingLeft: 12 + level * 14 }}
      onClick={() => onSelect(item)}
      title={item.path}
    >
      <span className={item.type === "directory" ? "folder-icon" : "file-icon"}>{item.type === "directory" ? "▸" : fileGlyph(item.name)}</span>
      <span>{item.name}</span>
    </button>
    {item.type === "directory" && item.children && <FileTree items={item.children} selected={selected} onSelect={onSelect} level={level + 1} />}
  </div>)}</>;
}

function fileGlyph(name: string) {
  if (/\.(docx?|pdf)$/i.test(name)) return "▤";
  if (/\.xlsx?$/i.test(name)) return "▦";
  if (/\.pptx?$/i.test(name)) return "▥";
  if (/\.(mmd|mermaid|dot)$/i.test(name)) return "◇";
  return "□";
}

