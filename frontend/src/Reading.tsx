import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Check,
  ChevronDown,
  ExternalLink,
  FileText,
  Save,
  X,
} from "lucide-react";
import type { Content, LearningNote } from "./types";
import { api, date, put } from "./api";

export function displayText(text: string) {
  return text.replace(
    /[（(]\s*source_ids\s*[：:]\s*\[\s*["']s\d+["'](?:\s*,\s*["']s\d+["'])*\s*\]\s*[）)]/g,
    "",
  );
}
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
          img: ({ src, alt }) => (
            <a href={src} target="_blank" rel="noreferrer">
              {alt || "查看原文图片"}
            </a>
          ),
          table: ({ children }) => (
            <div className="table-scroll">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {displayText(children)}
      </ReactMarkdown>
    </div>
  );
}
export function Reading({
  data,
  overview,
}: {
  data: LearningNote;
  overview: boolean;
}) {
  const content = data.note!;
  return (
    <div className="reading-layout">
      <aside className="toc">
        <span>本页内容</span>
        <a
          href="#reading-top"
          onClick={(e) => {
            e.preventDefault();
            document
              .getElementById("reading-top")
              ?.scrollIntoView({ behavior: "smooth" });
          }}
        >
          一页速览
        </a>
        {!overview &&
          content.sections.map((s, i) => (
            <button
              key={i}
              onClick={() =>
                document
                  .getElementById("section-" + i)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              {s.title}
            </button>
          ))}
        <div className="toc-foot">{date(data.created)}</div>
      </aside>
      <article className="reading-paper" id="reading-top">
        <div className="paper-meta">
          <span>{overview ? "快速看懂全貌" : "详细精读笔记"}</span>
          <span>来自你的材料</span>
        </div>
        <h1>{content.title}</h1>
        <p className="subtitle">{content.subtitle}</p>
        <div className="paper-divider" />
        <Markdown>{content.overview}</Markdown>
        {!overview &&
          content.sections.map((section, i) => (
            <section className="note-section" id={"section-" + i} key={i}>
              <h2>{section.title}</h2>
              <Markdown>{section.markdown}</Markdown>
            </section>
          ))}
        {content.limitations.length > 0 && (
          <section className="limitations">
            <h3>阅读时，记住这些边界</h3>
            <ul>
              {content.limitations.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </section>
        )}
        <div className="conclusion">
          <span>一句话记住</span>
          <p>{content.conclusion}</p>
        </div>
        <footer className="paper-footer">拾页整理 · {data.scope}</footer>
      </article>
    </div>
  );
}
export function Original({ data }: { data: LearningNote }) {
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(30);
  const matches = data.segments.filter((s) => s.text.includes(query));
  return (
    <section className="original-page">
      <div className="row spread">
        <div>
          <h2>回到原文</h2>
          <p>{data.scope}</p>
        </div>
        {data.source.kind === "file" ? (
          <a
            className="button secondary"
            href={"/api/notes/" + data.id + "/source"}
          >
            <FileText size={16} />
            下载原文件
          </a>
        ) : data.source.kind === "url" ? (
          <a
            className="button secondary"
            href={data.source.content}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={16} />
            打开来源
          </a>
        ) : null}
      </div>
      <input
        className="search-input"
        aria-label="搜索原文"
        placeholder="查找原文中的词句…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setShown(30);
        }}
      />
      <div className="segment-list">
        {matches.slice(0, shown).map((s) => (
          <section key={s.id} id={s.id}>
            <span className="source-label">
              {s.id} · {s.location}
            </span>
            <div className="source-text">{s.text}</div>
          </section>
        ))}
      </div>
      <p className="original-count">
        已显示 {Math.min(shown, matches.length)} / {matches.length}{" "}
        个段落，搜索会查找完整原文。
      </p>
      {shown < matches.length && (
        <button
          className="button secondary"
          onClick={() => setShown((n) => n + 30)}
        >
          继续查看原文
        </button>
      )}
    </section>
  );
}
export function Editor({
  data,
  onSaved,
  onClose,
  onError,
}: {
  data: LearningNote;
  onSaved: (n: LearningNote) => void;
  onClose: () => void;
  onError: (e: string) => void;
}) {
  const [value, setValue] = useState<Content>(() =>
    structuredClone(data.note!),
  );
  const [saving, setSaving] = useState(false);
  const [versions, setVersions] = useState<
    { revision: number; note: Content }[]
  >([]);
  const [showHistory, setShowHistory] = useState(false);
  const update = (key: keyof Content, v: unknown) =>
    setValue((old) => ({ ...old, [key]: v }));
  async function save() {
    setSaving(true);
    try {
      onSaved(
        await put("/notes/" + data.id, {
          revision: data.revision,
          note: value,
        }),
      );
      onClose();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="editor-wrap">
      <div className="row spread">
        <div>
          <h2>编辑这份笔记</h2>
          <p>修改会另存版本，相关课程和测试会提示更新。</p>
        </div>
        <button className="icon-button" aria-label="关闭编辑" onClick={onClose}>
          <X />
        </button>
      </div>
      <div className="row">
        <button
          className="button secondary"
          onClick={async () => {
            try {
              setVersions(await api("/notes/" + data.id + "/versions"));
              setShowHistory((v) => !v);
            } catch (e) {
              onError((e as Error).message);
            }
          }}
        >
          <ChevronDown size={15} />
          历史版本
        </button>
        {showHistory && (
          <select
            aria-label="选择历史版本"
            defaultValue=""
            onChange={(e) => {
              const item = versions.find(
                (v) => v.revision === Number(e.target.value),
              );
              if (item) setValue(item.note);
            }}
          >
            <option value="">选择版本恢复到编辑器</option>
            {versions.map((v) => (
              <option key={v.revision} value={v.revision}>
                版本 {v.revision}
              </option>
            ))}
          </select>
        )}
      </div>
      <label>
        标题
        <input
          value={value.title}
          onChange={(e) => update("title", e.target.value)}
        />
      </label>
      <label>
        引言
        <input
          value={value.subtitle}
          onChange={(e) => update("subtitle", e.target.value)}
        />
      </label>
      <label>
        一页速览 · Markdown
        <textarea
          rows={10}
          value={value.overview}
          onChange={(e) => update("overview", e.target.value)}
        />
      </label>
      {value.sections.map((s, i) => (
        <section className="edit-section" key={i}>
          <label>
            章节标题
            <input
              value={s.title}
              onChange={(e) => {
                const sections = [...value.sections];
                sections[i] = { ...s, title: e.target.value };
                update("sections", sections);
              }}
            />
          </label>
          <label>
            内容 · Markdown
            <textarea
              rows={10}
              value={s.markdown}
              onChange={(e) => {
                const sections = [...value.sections];
                sections[i] = { ...s, markdown: e.target.value };
                update("sections", sections);
              }}
            />
          </label>
          <label>
            脑图要点 · 每行一条
            <textarea
              rows={3}
              value={s.keypoints.join("\n")}
              onChange={(e) => {
                const sections = [...value.sections];
                sections[i] = {
                  ...s,
                  keypoints: e.target.value.split("\n").filter(Boolean),
                };
                update("sections", sections);
              }}
            />
          </label>
        </section>
      ))}
      <label>
        限制与待确认 · 每行一条
        <textarea
          rows={4}
          value={value.limitations.join("\n")}
          onChange={(e) =>
            update("limitations", e.target.value.split("\n").filter(Boolean))
          }
        />
      </label>
      <label>
        一句话总结
        <textarea
          rows={2}
          value={value.conclusion}
          onChange={(e) => update("conclusion", e.target.value)}
        />
      </label>
      <div className="sticky-actions">
        <button className="button secondary" onClick={onClose}>
          取消
        </button>
        <button className="button primary" disabled={saving} onClick={save}>
          {saving ? <span className="spinner" /> : <Save size={16} />}保存新版本
        </button>
        <span>
          <Check size={13} /> 原版本会保留
        </span>
      </div>
    </div>
  );
}
