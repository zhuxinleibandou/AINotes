import { useEffect, useRef, useState } from "react";
import { Download, Expand, Minus, Plus, RotateCcw } from "lucide-react";
import { toBlob } from "html-to-image";
import JSZip from "jszip";
import { api, download, filename } from "./api";
import { Markdown } from "./Reading";
import type { LearningNote, Section } from "./types";

async function remember(data: LearningNote, blob: Blob, name: string) {
  const form = new FormData();
  form.append("file", blob, name);
  form.append("revision", String(data.revision));
  await api("/notes/" + data.id + "/exports", { method: "POST", body: form });
  download(blob, name);
}
const kindLabels: Record<Section["kind"], string> = {
  concept: "概念",
  steps: "步骤",
  case: "案例",
  comparison: "对比",
  process: "流程",
  warning: "边界",
};
// Break exceptionally large blocks without discarding their inline markup.
function inlineParts(node: Element, size = 1200): HTMLElement[] {
  const texts: Text[] = [];
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) texts.push(walker.currentNode as Text);
  const length = texts.reduce((n, text) => n + text.length, 0);
  if (length <= size) return [node.cloneNode(true) as HTMLElement];
  const point = (offset: number): [Text, number] => {
    for (const text of texts) {
      if (offset <= text.length) return [text, offset];
      offset -= text.length;
    }
    return [texts[texts.length - 1], texts[texts.length - 1].length];
  };
  const parts: HTMLElement[] = [];
  for (let offset = 0; offset < length; offset += size) {
    const range = document.createRange();
    range.setStart(...point(offset));
    range.setEnd(...point(Math.min(offset + size, length)));
    const part = node.cloneNode(false) as HTMLElement;
    part.appendChild(range.cloneContents());
    parts.push(part);
  }
  return parts;
}
function exportBlocks(node: Element): HTMLElement[] {
  if (node.matches("ul,ol")) {
    // Preserve list numbering across split pages.
    return Array.from(node.children).flatMap((item, index) =>
      inlineParts(item).map((part) => {
        const list = node.cloneNode(false) as HTMLElement;
        if (list.tagName === "OL")
          list.setAttribute(
            "start",
            String(Number(node.getAttribute("start") || 1) + index),
          );
        list.appendChild(part);
        return list;
      }),
    );
  }
  if (node.matches(".table-scroll")) {
    const table = node.querySelector("table");
    if (table)
      return Array.from(table.querySelectorAll("tbody tr")).flatMap((row) => {
        const cells = Array.from(row.children).map((cell) => inlineParts(cell));
        const count = Math.max(1, ...cells.map((parts) => parts.length));
        return Array.from({ length: count }, (_, i) => {
          const wrapper = node.cloneNode(false) as HTMLElement;
          const piece = table.cloneNode(false) as HTMLElement;
          const head = table.querySelector("thead");
          if (head) piece.appendChild(head.cloneNode(true));
          const body = document.createElement("tbody"),
            newRow = document.createElement("tr");
          cells.forEach((parts, col) =>
            newRow.appendChild(parts[i] || row.children[col].cloneNode(false)),
          );
          body.appendChild(newRow);
          piece.appendChild(body);
          wrapper.appendChild(piece);
          return wrapper;
        });
      });
  }
  return inlineParts(node);
}
export function Poster({
  data,
  onError,
}: {
  data: LearningNote;
  onError: (s: string) => void;
}) {
  const outer = useRef<HTMLDivElement>(null),
    sheet = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.64),
    [height, setHeight] = useState(1200),
    [busy, setBusy] = useState(false),
    [compact, setCompact] = useState(true),
    [zoom, setZoom] = useState(1);
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      if (outer.current && sheet.current) {
        setScale(Math.min(outer.current.clientWidth / 1080, 1));
        setHeight(sheet.current.scrollHeight);
      }
    });
    if (outer.current) observer.observe(outer.current);
    if (sheet.current) observer.observe(sheet.current);
    return () => observer.disconnect();
  }, []);
  async function exportImage() {
    if (!sheet.current) return;
    setBusy(true);
    const stage = document.createElement("div");
    stage.className = "poster-export-stage";
    document.body.appendChild(stage);
    try {
      await document.fonts.ready;
      let page = document.createElement("div");
      page.className = sheet.current.className;
      stage.appendChild(page);
      const pages: HTMLDivElement[] = [page];
      const cards = Array.from(sheet.current.children);
      for (const card of cards) {
        // Keep each card intact. A very large card is split at its top-level paragraph boundaries.
        const clone = card.cloneNode(true) as HTMLElement;
        page.appendChild(clone);
        if (
          page.scrollHeight > 14000 &&
          page.children.length > 1 &&
          clone.scrollHeight <= 13500
        ) {
          page.removeChild(clone);
          page = document.createElement("div");
          page.className = sheet.current.className;
          stage.appendChild(page);
          pages.push(page);
          page.appendChild(clone);
        }
        if (clone.scrollHeight > 13500) {
          const body = clone.querySelector(
            ":scope > .poster-keypoints, :scope > .markdown",
          );
          if (body) {
            const paragraphs = Array.from(body.children).flatMap(exportBlocks);
            body.replaceChildren();
            let target = body;
            for (const paragraph of paragraphs) {
              target.appendChild(paragraph);
              if (page.scrollHeight > 14000 && target.children.length > 1) {
                target.removeChild(paragraph);
                page = document.createElement("div");
                page.className = sheet.current.className;
                stage.appendChild(page);
                pages.push(page);
                const continuation = document.createElement("section");
                continuation.className = clone.className;
                const heading = document.createElement("h2");
                heading.textContent = "接上页";
                continuation.appendChild(heading);
                target = document.createElement(body.tagName);
                target.className = body.className;
                continuation.appendChild(target);
                page.appendChild(continuation);
                target.appendChild(paragraph);
              }
            }
          }
        }
      }
      const blobs: Blob[] = [];
      if (pages.some((p) => p.scrollHeight > 14500))
        throw new Error(
          "单个模块过长，无法完整导出。请在编辑笔记中拆成多个段落或章节后重试。",
        );
      for (const p of pages) {
        const blob = await toBlob(p, {
          pixelRatio: 1,
          backgroundColor: "#f7f3ed",
          width: 1080,
          cacheBust: false,
        });
        if (!blob) throw new Error("长图导出失败，请重试。");
        blobs.push(blob);
      }
      if (blobs.length === 1)
        await remember(
          data,
          blobs[0],
          filename(data.title) + (compact ? "-要点" : "-完整") + ".png",
        );
      else {
        const zip = new JSZip();
        blobs.forEach((b, i) =>
          zip.file(String(i + 1).padStart(2, "0") + ".png", b),
        );
        await remember(
          data,
          await zip.generateAsync({ type: "blob" }),
          filename(data.title) + (compact ? "-要点长图.zip" : "-完整长图.zip"),
        );
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      stage.remove();
      setBusy(false);
    }
  }
  const note = data.note!;
  return (
    <div className="visual-page">
      <div className="visual-toolbar">
        <div>
          <strong>把重点，留在一张长图里</strong>
          <span>阅读卡片 · 1080px 高清导出 · 超长自动分图</span>
        </div>
        <div className="row">
          <div
            className="poster-content-switch"
            role="group"
            aria-label="长图内容"
          >
            <button
              aria-pressed={compact}
              disabled={busy}
              onClick={() => setCompact(true)}
            >
              要点版
            </button>
            <button
              aria-pressed={!compact}
              disabled={busy}
              onClick={() => setCompact(false)}
            >
              完整内容
            </button>
          </div>
          <button
            className="icon-button"
            aria-label="缩小长图"
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
          >
            <Minus size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="适宽显示"
            onClick={() => setZoom(1)}
          >
            <Expand size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="放大长图"
            onClick={() => setZoom((z) => Math.min(2, z + 0.25))}
          >
            <Plus size={16} />
          </button>
          <button
            className="button primary"
            onClick={exportImage}
            disabled={busy}
          >
            {busy ? <span className="spinner" /> : <Download size={16} />}
            导出长图
          </button>
        </div>
      </div>
      <div className="poster-viewport" ref={outer}>
        <div
          style={{
            height: height * scale * zoom,
            width: 1080 * scale * zoom,
            position: "relative",
          }}
        >
          <div
            className="poster-scaled"
            style={{ transform: `scale(${scale * zoom})` }}
          >
            <div
              ref={sheet}
              className={"poster-sheet" + (compact ? " poster-compact" : "")}
            >
              <header className="poster-card poster-heading">
                <span className="poster-label">
                  拾页 · {compact ? "要点长图" : "完整笔记"} ·{" "}
                  {data.source.kind === "url"
                    ? "链接材料"
                    : data.source.kind === "file"
                      ? "文件材料"
                      : "正文材料"}
                </span>
                <h1>{note.title}</h1>
                <p>{note.subtitle}</p>
                <div className="poster-heading-meta">
                  {note.sections.length} 个主题，读懂这份材料
                </div>
              </header>
              <section className="poster-card poster-lead">
                <h2 className="poster-lead-title">先看全貌</h2>
                <Markdown>
                  {compact ? note.overview.split(/\n\s*\n/)[0] : note.overview}
                </Markdown>
              </section>
              {note.sections.map((s, i) => (
                <section key={i} className={"poster-card poster-" + s.kind}>
                  <div className="poster-section-heading">
                    <h2>{s.title}</h2>
                    <span>{kindLabels[s.kind]}</span>
                  </div>
                  {compact && s.keypoints.length ? (
                    <ul className="poster-keypoints">
                      {s.keypoints.map((point, index) => (
                        <li key={index}>
                          <Markdown>{point}</Markdown>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <Markdown>{s.markdown}</Markdown>
                  )}
                </section>
              ))}
              {note.limitations.length > 0 && (
                <section className="poster-card poster-warning">
                  <div className="poster-section-heading">
                    <h2>阅读边界与待确认</h2>
                    <span>留意</span>
                  </div>
                  <ul>
                    {note.limitations.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </section>
              )}
              <section className="poster-card poster-ending">
                <span>一句话总结</span>
                <h2>{note.conclusion}</h2>
              </section>
              <footer className="poster-credit">
                <strong>拾页</strong>
                <span>{data.scope}</span>
                <span>
                  {data.source.kind === "url"
                    ? new URL(data.source.content!).hostname
                    : data.source.filename || "粘贴正文"}
                </span>
              </footer>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

type Node = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  parent: string | null;
  section?: number;
};
function wrap(value: string, max: number) {
  const chars = Array.from(value);
  const lines = [];
  for (let i = 0; i < chars.length; i += max)
    lines.push(chars.slice(i, i + max).join(""));
  return lines;
}
function layout(data: LearningNote, collapsed: Set<number>) {
  const nodes: Node[] = [];
  let cursor = 55;
  data.note!.sections.forEach((section, i) => {
    const points = collapsed.has(i) ? [] : section.keypoints;
    const kids: Node[] = [];
    points.forEach((label, j) => {
      const height = Math.max(60, wrap(label, 21).length * 23 + 26);
      kids.push({
        id: `p${i}-${j}`,
        x: 655,
        y: cursor,
        width: 330,
        height,
        label,
        parent: "s" + i,
      });
      cursor += height + 18;
    });
    const height = Math.max(70, wrap(section.title, 13).length * 24 + 26);
    const center = kids.length
      ? (kids[0].y + kids[kids.length - 1].y + kids[kids.length - 1].height) / 2
      : cursor + height / 2;
    nodes.push(
      {
        id: "s" + i,
        x: 335,
        y: center - height / 2,
        width: 245,
        height,
        label: section.title,
        parent: "root",
        section: i,
      },
      ...kids,
    );
    cursor = Math.max(cursor, center + height / 2) + 36;
  });
  const height = Math.max(cursor + 20, 450),
    rootHeight = Math.max(95, wrap(data.title, 12).length * 26 + 28);
  nodes.unshift({
    id: "root",
    x: 25,
    y: height / 2 - rootHeight / 2,
    width: 240,
    height: rootHeight,
    label: data.title,
    parent: null,
  });
  return { nodes, height };
}
export function Mindmap({
  data,
  onError,
}: {
  data: LearningNote;
  onError: (s: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set()),
    [zoom, setZoom] = useState(0.85),
    [selected, setSelected] = useState<Node | null>(null),
    [busy, setBusy] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const graph = layout(data, collapsed);
  useEffect(() => {
    const container = document.getElementById("map-scroll");
    if (container)
      container.scrollTop = Math.max(
        0,
        (graph.height * zoom - container.clientHeight) / 2,
      );
  }, [graph.height, zoom]);
  function toggle(i: number) {
    setCollapsed((old) => {
      const next = new Set(old);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }
  async function save(png: boolean) {
    if (!svg.current) return;
    setBusy(true);
    try {
      const element = svg.current.cloneNode(true) as SVGSVGElement;
      element.setAttribute("width", "1020");
      element.setAttribute("height", String(graph.height));
      const text = new XMLSerializer().serializeToString(element),
        blob = new Blob([text], { type: "image/svg+xml;charset=utf-8" });
      if (!png) {
        await remember(data, blob, filename(data.title) + ".svg");
        return;
      }
      const url = URL.createObjectURL(blob);
      try {
        const img = new Image();
        img.src = url;
        await img.decode();
        const canvas = document.createElement("canvas");
        canvas.width = 1020;
        canvas.height = graph.height;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("浏览器不能生成图片。");
        ctx.fillStyle = "#f7f3ed";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0);
        const out = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob(resolve),
        );
        if (out) await remember(data, out, filename(data.title) + "-脑图.png");
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="visual-page">
      <div className="visual-toolbar">
        <div>
          <strong>看清知识之间的联系</strong>
          <span>点击节点看来源，双击章节收起或展开</span>
        </div>
        <div className="row">
          <button
            className="icon-button"
            aria-label="缩小脑图"
            onClick={() => setZoom((v) => Math.max(0.3, v - 0.15))}
          >
            <Minus size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="脑图回到中心"
            onClick={() => {
              setZoom(0.85);
              const container = document.getElementById("map-scroll");
              if (container)
                container.scrollTo(
                  0,
                  Math.max(
                    0,
                    (graph.height * 0.85 - container.clientHeight) / 2,
                  ),
                );
            }}
          >
            <RotateCcw size={15} />
          </button>
          <button
            className="icon-button"
            aria-label="放大脑图"
            onClick={() => setZoom((v) => Math.min(2, v + 0.15))}
          >
            <Plus size={16} />
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => save(false)}
          >
            SVG
          </button>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => save(true)}
          >
            <Download size={15} />
            PNG
          </button>
        </div>
      </div>
      <div className="mindmap-scroll" id="map-scroll">
        <svg
          ref={svg}
          xmlns="http://www.w3.org/2000/svg"
          width={1020 * zoom}
          height={graph.height * zoom}
          viewBox={`0 0 1020 ${graph.height}`}
          role="img"
          aria-label="笔记知识脑图"
          style={{
            background: "#f7f3ed",
            fontFamily: "PingFang SC, sans-serif",
          }}
        >
          {graph.nodes
            .filter((n) => n.parent)
            .map((n) => {
              const p = graph.nodes.find((p) => p.id === n.parent)!;
              return (
                <path
                  key={n.id + "line"}
                  d={`M${p.x + p.width},${p.y + p.height / 2} C${p.x + p.width + 35},${p.y + p.height / 2} ${n.x - 35},${n.y + n.height / 2} ${n.x},${n.y + n.height / 2}`}
                  fill="none"
                  stroke="#dcbfae"
                  strokeWidth="2"
                />
              );
            })}
          {graph.nodes.map((n) => (
            <g
              key={n.id}
              role="button"
              tabIndex={0}
              aria-label={n.label}
              style={{ cursor: "pointer" }}
              onClick={() => setSelected(n)}
              onDoubleClick={() => {
                if (n.section !== undefined) toggle(n.section);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setSelected(n);
                  if (n.section !== undefined) toggle(n.section);
                }
              }}
            >
              <rect
                x={n.x}
                y={n.y}
                width={n.width}
                height={n.height}
                rx={n.id === "root" ? 18 : 12}
                fill={
                  n.id === "root"
                    ? "#db825f"
                    : n.section !== undefined
                      ? "#fff0e5"
                      : "#fffdfa"
                }
                stroke={selected?.id === n.id ? "#ba603d" : "#e7cdbb"}
                strokeWidth="1.5"
              />
              {wrap(
                n.label,
                n.id === "root" ? 12 : n.section !== undefined ? 13 : 21,
              ).map((line, i) => (
                <text
                  x={n.x + 18}
                  y={n.y + 29 + i * (n.id === "root" ? 26 : 23)}
                  key={i}
                  fill={n.id === "root" ? "#fffdfa" : "#493c31"}
                  fontSize={
                    n.id === "root" ? 20 : n.section !== undefined ? 18 : 15
                  }
                  fontWeight={n.parent === "root" || !n.parent ? 600 : 400}
                >
                  {line}
                </text>
              ))}
            </g>
          ))}
        </svg>
      </div>
      {selected && (
        <div className="map-detail">
          <strong>{selected.label}</strong>
          <div className="row">
            {selected.section !== undefined && (
              <button
                className="button secondary"
                onClick={() => toggle(selected.section!)}
              >
                {collapsed.has(selected.section) ? "展开要点" : "收起要点"}
              </button>
            )}
          </div>
        </div>
      )}
      <a
        className="text-button map-outline"
        href={`/api/notes/${data.id}/export/outline`}
      >
        下载 Markdown 大纲
      </a>
    </div>
  );
}
