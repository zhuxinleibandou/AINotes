import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowUpRight,
  AudioLines,
  BookMarked,
  BookOpen,
  Check,
  ChevronDown,
  CircleHelp,
  Copy,
  Download,
  FileText,
  FolderOpen,
  Image,
  LayoutGrid,
  Link,
  List,
  Loader2,
  Mic,
  Network,
  NotebookPen,
  Pause,
  Pencil,
  Play,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Square,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import type {
  Format,
  Job,
  LearningNote,
  NoteCard,
  Progress,
  QuizData,
  Settings,
} from "./types";
import { api, date, download, post, put } from "./api";
import { Editor, Original, Reading } from "./Reading";
import { ModelSettings } from "./ModelSettings";
import { CourseView, GenerateEmpty, Quiz, LearningHistory } from "./Learning";
const Poster = lazy(() =>
  import("./Visuals").then((m) => ({ default: m.Poster })),
);
const Mindmap = lazy(() =>
  import("./Visuals").then((m) => ({ default: m.Mindmap })),
);
const active = (job: Job | null) =>
  !!job && ["running", "queued", "pausing", "cancelling"].includes(job.status);
type Tab =
  | "overview"
  | "markdown"
  | "poster"
  | "mindmap"
  | "course"
  | "quiz"
  | "source";
function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const f = () => setHash(location.hash);
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return hash;
}
function Logo() {
  return (
    <a className="brand" href="#">
      <span className="brand-symbol">
        <NotebookPen size={25} strokeWidth={1.5} />
      </span>
      <strong>拾页</strong>
      <span className="brand-subtitle">把材料，变成学会</span>
    </a>
  );
}
function Status({ settings }: { settings: Settings | null }) {
  if (
    settings &&
    settings.generation_backend &&
    settings.generation_backend !== "codex"
  ) {
    const provider =
      settings.generation_backend === "local"
        ? settings.local_provider
        : settings.api_provider;
    return (
      <span className="connection model-selected">
        <i />
        {settings.generation_backend === "local"
          ? "本地模型"
          : "模型API"} ·{" "}
        {settings.provider_presets?.[provider]?.label || provider}
      </span>
    );
  }
  return (
    <span
      className={"connection " + (settings?.codex_logged_in ? "connected" : "")}
    >
      <i />
      {settings?.codex_logged_in ? "Codex 已就绪" : "检查 Codex 连接"}
    </span>
  );
}
function Recording({
  onFile,
  onError,
}: {
  onFile: (f: File) => void;
  onError: (s: string) => void;
}) {
  const [state, setState] = useState<"idle" | "recording" | "paused" | "ready">(
      "idle",
    ),
    [seconds, setSeconds] = useState(0),
    [blob, setBlob] = useState<Blob | null>(null),
    [url, setUrl] = useState("");
  const [starting, setStarting] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null),
    stream = useRef<MediaStream | null>(null),
    chunks = useRef<Blob[]>([]),
    timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (state === "recording")
      timer.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [state]);
  useEffect(
    () => () => {
      if (recorder.current?.state !== "inactive") recorder.current?.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );
  useEffect(() => {
    if (!blob) return;
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  useEffect(() => {
    if (state === "idle") return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [state]);
  useEffect(() => {
    const pauseOnLeave = () => {
      if (recorder.current?.state === "recording") {
        recorder.current.pause();
        setState("paused");
        onError("录音已暂停，回到新建笔记可继续或保存。");
      }
    };
    window.addEventListener("hashchange", pauseOnLeave);
    return () => window.removeEventListener("hashchange", pauseOnLeave);
  }, [onError]);
  async function start() {
    if (starting) return;
    setStarting(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error(
          "浏览器不支持录音。请使用最新版 Safari 或 Chrome 打开本机地址。",
        );
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      if (
        location.hash.startsWith("#note/") ||
        ["#library", "#settings"].includes(location.hash)
      )
        throw new Error("页面已切换，已停止麦克风。回到新建笔记可重新录音。");
      const mime = ["audio/webm;codecs=opus", "audio/mp4"].find((m) =>
        MediaRecorder.isTypeSupported(m),
      );
      recorder.current = new MediaRecorder(
        stream.current,
        mime ? { mimeType: mime } : undefined,
      );
      chunks.current = [];
      setBlob(null);
      setSeconds(0);
      recorder.current.ondataavailable = (e) => {
        if (e.data.size) chunks.current.push(e.data);
      };
      recorder.current.onstop = () => {
        const audio = new Blob(chunks.current, {
          type: recorder.current?.mimeType || "audio/webm",
        });
        if (audio.size) {
          setBlob(audio);
          setState("ready");
        } else {
          setState("idle");
          onError("没有录到有效音频，请检查麦克风后重试。");
        }
        stream.current?.getTracks().forEach((t) => t.stop());
      };
      recorder.current.onerror = () => {
        stream.current?.getTracks().forEach((t) => t.stop());
        onError("录音被浏览器中断，请先保存已录制部分，再重新录制。");
      };
      recorder.current.start(1000);
      setState("recording");
    } catch (e) {
      stream.current?.getTracks().forEach((t) => t.stop());
      setState("idle");
      onError(
        (e as Error).name === "NotAllowedError"
          ? "麦克风权限未开启。请在浏览器中允许录音，或上传已有音频。"
          : (e as Error).message,
      );
    } finally {
      setStarting(false);
    }
  }
  function useRecording() {
    if (!blob) return;
    onFile(
      new File(
        [blob],
        "现场录音-" +
          new Date().toISOString().slice(0, 10) +
          (blob.type.includes("mp4") ? ".m4a" : ".webm"),
        { type: blob.type },
      ),
    );
  }
  return (
    <div className="recorder">
      <div className={"mic-orb " + (state === "recording" ? "recording" : "")}>
        <Mic size={29} />
      </div>
      <h3>
        {state === "idle"
          ? "把正在发生的知识，录下来"
          : state === "recording"
            ? "正在录音"
            : state === "paused"
              ? "录音已暂停"
              : "这段录音，准备好了"}
      </h3>
      <div className="record-time">
        {String(Math.floor(seconds / 3600)).padStart(2, "0")}:
        {String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:
        {String(seconds % 60).padStart(2, "0")}
      </div>
      {state === "idle" ? (
        <>
          <p>课堂、会议或自己的想法。结束后在本机转写，再整理成笔记。</p>
          <button
            className="button primary"
            onClick={start}
            disabled={starting}
          >
            <Mic size={17} />
            {starting ? "正在请求麦克风…" : "开始录音"}
          </button>
        </>
      ) : state === "ready" ? (
        <>
          <audio controls src={url} />
          <div className="row centered">
            <button
              className="button secondary"
              onClick={() => {
                if (blob)
                  download(
                    blob,
                    "现场录音" + (blob.type.includes("mp4") ? ".m4a" : ".webm"),
                  );
              }}
            >
              <Download size={16} />
              下载录音
            </button>
            <button className="button primary" onClick={useRecording}>
              <Check size={16} />
              使用这段录音
            </button>
          </div>
          <button
            className="text-button"
            onClick={() => {
              setState("idle");
              setBlob(null);
              setSeconds(0);
            }}
          >
            重新录制
          </button>
        </>
      ) : (
        <div className="row centered">
          <button
            className="button secondary"
            onClick={() => {
              if (state === "recording") {
                recorder.current?.pause();
                setState("paused");
              } else {
                recorder.current?.resume();
                setState("recording");
              }
            }}
          >
            {state === "paused" ? <Play size={16} /> : <Pause size={16} />}{" "}
            {state === "paused" ? "继续" : "暂停"}
          </button>
          <button
            className="button primary"
            onClick={() => recorder.current?.stop()}
          >
            <Square size={15} />
            结束录音
          </button>
        </div>
      )}
      <span className="record-notice">
        录音保留在当前页面，结束后请提交或下载保存。
      </span>
    </div>
  );
}
function NoteList({
  notes,
  onOpen,
  compact = false,
}: {
  notes: NoteCard[];
  onOpen: (id: string) => void;
  compact?: boolean;
}) {
  if (!notes.length)
    return (
      <div className="library-empty">
        <div className="empty-books">
          <BookOpen size={35} />
          <span>你的第一份学习笔记</span>
        </div>
        <h3>从一份好奇的材料开始</h3>
        <p>
          放进一篇文章、一段视频或一份课件，
          <br />
          把值得留下的知识，放在这里。
        </p>
      </div>
    );
  return (
    <div className={"notes-grid " + (compact ? "compact" : "")}>
      {notes.map((note) => (
        <button
          className="note-card"
          key={note.id}
          onClick={() => onOpen(note.id)}
        >
          <div className="note-card-top">
            <span className={"source-icon " + note.source.kind}>
              {note.source.kind === "url" ? (
                <Link size={19} />
              ) : note.source.kind === "file" ? (
                <FileText size={19} />
              ) : (
                <NotebookPen size={19} />
              )}
            </span>
            <span>{date(note.created)}</span>
            <ArrowUpRight size={16} />
          </div>
          <h3>{note.title}</h3>
          <p>{note.subtitle || note.job?.stage || "等待整理"}</p>
          <div className="note-card-bottom">
            <span>
              {note.source.kind === "url"
                ? "链接笔记"
                : note.source.kind === "file"
                  ? "文件笔记"
                  : "正文笔记"}
            </span>
            <span
              className={
                active(note.job)
                  ? "processing-label"
                  : note.ready
                    ? "ready-label"
                    : "muted"
              }
            >
              {active(note.job) ? (
                <>
                  <Loader2 size={12} className="spin" />
                  处理中
                </>
              ) : note.job?.status === "paused" ? (
                "已暂停"
              ) : note.ready ? (
                "已整理"
              ) : note.job?.status === "failed" ? (
                "待重试"
              ) : (
                "未完成"
              )}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}
function Home({
  notes,
  settings,
  onImported,
  onRefresh,
  onError,
}: {
  notes: NoteCard[];
  settings: Settings | null;
  onImported: (id: string, tab: Tab) => void;
  onRefresh: () => void;
  onError: (s: string) => void;
}) {
  const [mode, setMode] = useState<"url" | "file" | "text" | "record">(
      location.hash === "#new/file"
        ? "file"
        : location.hash === "#new/text"
          ? "text"
          : "url",
    ),
    [content, setContent] = useState(""),
    [files, setFiles] = useState<
      {
        key: string;
        file: File;
        status: "pending" | "uploading" | "imported" | "failed";
        noteId?: string;
        error?: string;
      }[]
    >([]),
    [instructions, setInstructions] = useState(""),
    [format, setFormat] = useState<Format>("poster"),
    [course, setCourse] = useState(false),
    [busy, setBusy] = useState(false),
    [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null),
    textInput = useRef<HTMLInputElement>(null),
    stopImport = useRef(false);
  const remaining = files.filter((f) => f.status !== "imported").length;
  function chooseFiles(selected: File[]) {
    if (busy) return;
    const valid = selected.filter((f) => f.size <= 500 * 1024 * 1024);
    if (valid.length < selected.length)
      onError("已跳过超过500MB的文件，请分段后再添加。其他文件可以继续导入。");
    setFiles((old) => [
      ...old,
      ...valid.map((file) => ({
        key: crypto.randomUUID(),
        file,
        status: "pending" as const,
      })),
    ]);
    setMode("file");
  }
  async function importText(file: File) {
    setBusy(true);
    try {
      const bytes = await file.arrayBuffer();
      const header = new Uint8Array(bytes, 0, Math.min(2, bytes.byteLength));
      let text: string;
      if (header[0] === 0xff && header[1] === 0xfe)
        text = new TextDecoder("utf-16le", { fatal: true }).decode(bytes);
      else if (header[0] === 0xfe && header[1] === 0xff)
        text = new TextDecoder("utf-16be", { fatal: true }).decode(bytes);
      else {
        try {
          text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        } catch {
          text = new TextDecoder("gb18030", { fatal: true }).decode(bytes);
        }
      }
      setContent(text);
      setMode("text");
    } catch {
      onError("无法读取文本，请将文件另存为UTF-8后重试。");
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    setBusy(true);
    stopImport.current = false;
    try {
      let result: { note: LearningNote; job: Job };
      if (mode === "file") {
        if (!remaining) throw new Error("请先添加文件。");
        // One file per request avoids multipart count limits and keeps failures independent.
        const pending = files.filter((f) => f.status !== "imported");
        for (const entry of pending) {
          if (stopImport.current) break;
          const update = (patch: Partial<typeof entry>) =>
            setFiles((old) =>
              old.map((f) => (f.key === entry.key ? { ...f, ...patch } : f)),
            );
          update({ status: "uploading", error: undefined });
          try {
            const form = new FormData();
            form.append("file", entry.file);
            form.append("instructions", instructions);
            form.append("format", format);
            form.append("mode", course ? "course" : "summary");
            result = await api("/import/file", { method: "POST", body: form });
            update({ status: "imported", noteId: result.note.id });
            onRefresh();
            if (files.length === 1)
              onImported(result.note.id, course ? "course" : format);
          } catch (e) {
            update({ status: "failed", error: (e as Error).message });
          }
        }
        return;
      } else {
        result = await post("/import", {
          kind: mode === "url" ? "url" : "text",
          content,
          instructions,
          format,
          mode: course ? "course" : "summary",
        });
      }
      onImported(result.note.id, course ? "course" : format);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="home">
      <section className="home-intro">
        <span className="intro-mark">
          <Sparkles size={15} />
          知识值得慢慢消化，准备可以快一点
        </span>
        <h1>今天想学什么？</h1>
        <p>把视频、文章与课件，变成真正读得懂的笔记。</p>
      </section>
      <section
        className={"composer " + (dragging ? "dragging" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length)
            chooseFiles(Array.from(e.dataTransfer.files));
        }}
      >
        <div className="input-tabs" role="tablist" aria-label="材料来源">
          {(
            [
              { id: "url", icon: Link, label: "粘贴链接" },
              { id: "file", icon: Upload, label: "上传文件" },
              { id: "text", icon: FileText, label: "粘贴正文" },
              { id: "record", icon: Mic, label: "现场录音" },
            ] as const
          ).map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={mode === t.id}
              disabled={busy}
              className={mode === t.id ? "selected" : ""}
              onClick={() => setMode(t.id)}
            >
              <t.icon size={17} />
              {t.label}
            </button>
          ))}
        </div>
        <div hidden={mode !== "record"}>
          <Recording onFile={(file) => chooseFiles([file])} onError={onError} />
        </div>
        {mode !== "record" && (
          <>
            <div className="input-area">
              {mode === "file" ? (
                <div className="file-drop">
                  <input
                    ref={fileInput}
                    type="file"
                    multiple
                    onChange={(e) => {
                      if (e.target.files)
                        chooseFiles(Array.from(e.target.files));
                      e.target.value = "";
                    }}
                    aria-label="选择学习文件"
                    hidden
                    accept=".pdf,.docx,.pptx,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.heic,.mp3,.wav,.m4a,.aac,.flac,.mp4,.mov,.mkv,.webm,.ogg,.avi,.m4v,.bmp,.tiff"
                  />
                  {files.length ? (
                    <>
                      <div className="batch-heading">
                        <div>
                          <strong>{files.length} 份材料</strong>
                          <span>每份单独建立笔记，按顺序处理</span>
                        </div>
                        <button
                          className="button secondary"
                          disabled={busy}
                          onClick={() => fileInput.current?.click()}
                        >
                          <Plus size={15} />
                          继续添加
                        </button>
                      </div>
                      <ul className="batch-files" aria-label="待导入文件">
                        {files.map((entry) => (
                          <li key={entry.key}>
                            <FileText size={19} />
                            <div className="batch-file-info">
                              <strong>{entry.file.name}</strong>
                              <span>
                                {(entry.file.size / 1024 / 1024).toFixed(2)} MB
                              </span>
                              {entry.error && <p role="alert">{entry.error}</p>}
                            </div>
                            {entry.status === "imported" ? (
                              <button
                                className="text-button"
                                onClick={() =>
                                  onImported(
                                    entry.noteId!,
                                    course ? "course" : format,
                                  )
                                }
                              >
                                查看笔记
                              </button>
                            ) : entry.status === "uploading" ? (
                              <span className="batch-status" role="status">
                                <Loader2 size={14} className="spin" />
                                导入中
                              </span>
                            ) : (
                              <>
                                <span className="batch-status">
                                  {entry.status === "failed"
                                    ? "待重试"
                                    : "待导入"}
                                </span>
                                <button
                                  className="icon-button"
                                  aria-label={"移除" + entry.file.name}
                                  disabled={busy}
                                  onClick={() =>
                                    setFiles((old) =>
                                      old.filter((f) => f.key !== entry.key),
                                    )
                                  }
                                >
                                  <X size={16} />
                                </button>
                              </>
                            )}
                          </li>
                        ))}
                      </ul>
                      <p className="batch-notice" aria-live="polite">
                        已导入{" "}
                        {files.filter((f) => f.status === "imported").length} /{" "}
                        {files.length} 份 ·
                        文件数量不限，每个最大500MB。已导入的材料关闭页面后仍会继续整理。
                      </p>
                      {busy && (
                        <button
                          className="text-button"
                          onClick={() => {
                            stopImport.current = true;
                          }}
                        >
                          停止后续导入
                        </button>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="upload-icon">
                        <Upload size={27} />
                      </span>
                      <h3>把材料拖进来，或点击选择</h3>
                      <p>PDF、Word、PPT、文本、图片和音视频</p>
                      <button
                        className="button secondary"
                        onClick={() => fileInput.current?.click()}
                      >
                        选择文件
                      </button>
                      <span>
                        支持多选与拖入多个文件 · 数量不限 · 每个最大500MB
                      </span>
                    </>
                  )}
                </div>
              ) : (
                <>
                  <textarea
                    aria-label={mode === "url" ? "材料链接" : "材料正文"}
                    className={
                      "material-input " + (mode === "text" ? "body-input" : "")
                    }
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder={
                      mode === "url"
                        ? "粘贴一个你想学会的链接…"
                        : "把文章、课程文字稿，或你正在研究的内容粘贴到这里…"
                    }
                  />
                  <div className="input-help">
                    {mode === "url" ? (
                      <>
                        <Link size={13} />
                        B站、抖音、YouTube、小宇宙、公众号与公开网页 ·
                        音视频最长600分钟
                      </>
                    ) : (
                      <>
                        <FileText size={13} />
                        <span>
                          {content.length.toLocaleString()} 字 ·
                          长文本自动分段整理，保留完整原文
                        </span>
                        <input
                          ref={textInput}
                          type="file"
                          accept=".txt,.md,.markdown"
                          aria-label="导入长文本文件"
                          hidden
                          onChange={(e) => {
                            if (e.target.files?.[0])
                              void importText(e.target.files[0]);
                            e.target.value = "";
                          }}
                        />
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() => textInput.current?.click()}
                        >
                          从TXT / Markdown导入
                        </button>
                      </>
                    )}
                  </div>
                </>
              )}
            </div>
            <div className="requirements">
              <span>
                <Pencil size={14} />
                学习要求
              </span>
              <input
                aria-label="学习要求"
                placeholder="可选，例如：重点整理方法步骤，保留案例和关键数字"
                value={instructions}
                maxLength={4000}
                onChange={(e) => setInstructions(e.target.value)}
              />
            </div>
            <div className="composer-footer">
              <div className="generation-controls">
                <div className="format-select">
                  <span>总结为</span>
                  <select
                    aria-label="总结格式"
                    value={format}
                    onChange={(e) => setFormat(e.target.value as Format)}
                  >
                    <option value="poster">长图笔记</option>
                    <option value="markdown">Markdown</option>
                    <option value="mindmap">思维导图</option>
                  </select>
                  <ChevronDown size={13} />
                </div>
                <label className={"course-check " + (course ? "checked" : "")}>
                  <input
                    type="checkbox"
                    checked={course}
                    onChange={(e) => setCourse(e.target.checked)}
                  />
                  <BookOpen size={15} />
                  同时准备课程
                </label>
              </div>
              <button
                className="button primary generate-button"
                onClick={submit}
                disabled={
                  busy || (mode === "file" ? !remaining : !content.trim())
                }
              >
                {busy ? (
                  <Loader2 size={17} className="spin" />
                ) : (
                  <Sparkles size={17} />
                )}{" "}
                {busy
                  ? "正在提交…"
                  : mode === "file" && files.length
                    ? remaining
                      ? `整理 ${remaining} 份材料`
                      : "已全部导入"
                    : "开始整理"}
              </button>
            </div>
          </>
        )}
      </section>
      <div className="local-note">
        <span>
          <span className="tiny-dot" />
          资料保存在本机
        </span>
        <span>语音在本地转写</span>
        <span>
          {settings?.generation_backend === "local"
            ? "内容由本地模型分析"
            : settings?.generation_backend === "api"
              ? "内容交由所选API模型分析"
              : "内容交由 Codex 分析"}
        </span>
      </div>
      <section className="recent-section">
        <div className="section-heading">
          <div>
            <h2>
              我的笔记<span>{notes.length.toString().padStart(2, "0")}</span>
            </h2>
            <p>留住重点，下次回来接着学。</p>
          </div>
          <a className="text-button" href="#library">
            查看全部 <ArrowUpRight size={15} />
          </a>
        </div>
        <NoteList
          notes={notes.slice(0, 6)}
          compact
          onOpen={(id) => onImported(id, "overview")}
        />
      </section>
      <div className="how-strip">
        <div>
          <span>读懂</span>
          <p>一页速览，先看全貌</p>
        </div>
        <i />
        <div>
          <span>留下</span>
          <p>笔记、长图、脑图</p>
        </div>
        <i />
        <div>
          <span>学会</span>
          <p>分节课程，边学边测</p>
        </div>
      </div>
    </main>
  );
}
function SettingsPage({
  settings,
  onRefresh,
  onError,
}: {
  settings: Settings | null;
  onRefresh: () => void;
  onError: (s: string) => void;
}) {
  const [whisper, setWhisper] = useState(
      settings?.whisper_model || "mlx-community/whisper-large-v3-turbo",
    ),
    [saved, setSaved] = useState(false);
  useEffect(() => {
    if (settings) {
      setWhisper(settings.whisper_model);
    }
  }, [settings?.whisper_model]);
  async function save() {
    try {
      await put("/settings", { whisper_model: whisper });
      setSaved(true);
      onRefresh();
    } catch (e) {
      onError((e as Error).message);
    }
  }
  return (
    <main className="settings-page">
      <a className="back-link" href="#">
        <ArrowLeft size={16} />
        返回首页
      </a>
      <span className="eyebrow">本地学习空间</span>
      <h1>把工具，调成顺手的样子</h1>
      <p className="subtitle">
        资料与进度保存在这台 Mac，可以选择模型API、本地模型或已有Codex登录。
      </p>
      <ModelSettings
        settings={settings}
        onRefresh={onRefresh}
        onError={onError}
      />
      <section className="settings-card">
        <div className="row spread">
          <h2>Codex 连接</h2>
          {settings?.generation_backend === "codex" && (
            <Status settings={settings} />
          )}
        </div>
        <p>
          {settings?.codex_available
            ? settings.codex_logged_in
              ? "已找到本机 Codex 并检测到登录状态。实际可用性以生成成功为准。"
              : "请先在终端运行 codex login 完成登录。"
            : "没有找到 Codex 命令行，请先安装并登录。"}
        </p>
      </section>
      <section className="settings-card">
        <h2>语音与文件</h2>
        <label>
          本地语音识别模型
          <select
            value={whisper}
            onChange={(e) => {
              setWhisper(e.target.value);
              setSaved(false);
            }}
          >
            <option value="mlx-community/whisper-large-v3-turbo">
              Whisper large-v3-turbo · 默认，更准确
            </option>
            <option value="mlx-community/whisper-small-mlx">
              Whisper small · 更小，下载更快
            </option>
          </select>
        </label>
        <p>
          首次转写会下载所选模型，之后可以离线识别。视频默认先分析语音，画面分析按需开启。
        </p>
        <div className="capability-list">
          <span>
            <Check size={15} />{" "}
            {settings?.ffmpeg ? "FFmpeg 可用" : "FFmpeg 未安装"}
          </span>
          <span>
            <Check size={15} />{" "}
            {settings?.ocr
              ? "Apple 本地 OCR 可用"
              : "OCR 需要 Apple 命令行工具"}
          </span>
        </div>
      </section>
      <section className="settings-card">
        <h2>平台访问授权 · 可选</h2>
        <p>
          抖音会先自动尝试公开分享页，通常无需导入 Cookie。如平台仍限制访问，
          可选导入自己的 Netscape 格式 cookies.txt 作为后备。仅保存到本机，
          用于读取你有权访问的链接，不会发送给生成模型。
        </p>
        {(["douyin", "bilibili", "youtube"] as const).map((platform) => (
          <div className="cookie-row" key={platform}>
            <span>
              {platform === "douyin"
                ? "抖音"
                : platform === "bilibili"
                  ? "B站"
                  : "YouTube"}{" "}
              · {settings?.platform_cookies?.[platform] ? "已配置" : "未配置"}
            </span>
            <label className="button secondary">
              导入 Cookie
              <input
                type="file"
                accept=".txt"
                hidden
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  const form = new FormData();
                  form.append("platform", platform);
                  form.append("file", f);
                  try {
                    await api("/settings/platform-cookies", {
                      method: "POST",
                      body: form,
                    });
                    onRefresh();
                  } catch (error) {
                    onError((error as Error).message);
                  }
                  e.target.value = "";
                }}
              />
            </label>
            {settings?.platform_cookies?.[platform] && (
              <button
                className="text-button"
                onClick={async () => {
                  try {
                    await post(
                      "/settings/platform-cookies/" + platform + "/remove",
                    );
                    onRefresh();
                  } catch (error) {
                    onError((error as Error).message);
                  }
                }}
              >
                移除
              </button>
            )}
          </div>
        ))}
      </section>
      <section className="settings-card">
        <h2>你的资料在哪里</h2>
        <code>{settings?.storage || "正在读取…"}</code>
        <p>
          可用磁盘约 {settings?.free_gb ?? "…"}{" "}
          GB。原材料、笔记版本、进度与导出文件分别保留。
        </p>
        <button
          className="button secondary"
          onClick={async () => {
            try {
              const result = await post<{ freed_bytes: number }>(
                "/settings/clear-cache",
              );
              onError(
                "临时缓存已清理，释放 " +
                  (result.freed_bytes / 1024 / 1024).toFixed(1) +
                  " MB。资料和导出文件已保留。",
              );
            } catch (e) {
              onError((e as Error).message);
            }
          }}
        >
          <Trash2 size={15} />
          清理临时缓存
        </button>
      </section>
      <button
        className="button primary"
        disabled={!!settings?.active_tasks?.length}
        onClick={save}
      >
        {saved ? <Check size={16} /> : <Settings2 size={16} />}{" "}
        {saved ? "语音设置已保存" : "保存语音设置"}
      </button>
    </main>
  );
}
function TaskBanner({
  job,
  onCancel,
  onRetry,
}: {
  job: Job;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    if (!active(job)) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job.status]);
  if (job.status === "completed") return null;
  const working = active(job),
    elapsed = Math.max(0, Math.floor((clock - job.created * 1000) / 1000));
  const steps = ["读取材料", "分析结构", "整理内容", "保存结果"];
  const step =
    job.stage.includes("解析") ||
    job.stage.includes("获取") ||
    job.stage.includes("转写") ||
    job.status === "queued"
      ? 0
      : job.stage.includes("分段")
        ? 1
        : 2;
  return (
    <section
      className={"task-banner " + (working ? "working" : "failed")}
      role="status"
    >
      <div className="task-main">
        <span className="task-icon">
          {working ? (
            <Loader2 className="spin" size={23} />
          ) : (
            <CircleHelp size={23} />
          )}
        </span>
        <div>
          <strong>{job.stage}</strong>
          <p>
            {working
              ? ["pausing", "cancelling"].includes(job.status)
                ? "正在停止当前处理，已完成的内容会保留。"
                : `离开页面也会继续处理 · 已用 ${Math.floor(elapsed / 60)}分${elapsed % 60}秒`
              : job.error || "已完成的解析步骤仍保留，可以继续处理。"}
          </p>
        </div>
        <button
          className="button secondary"
          disabled={job.status === "cancelling"}
          onClick={working ? onCancel : onRetry}
        >
          {working ? "取消任务" : "继续处理"}
        </button>
      </div>
      {working && (
        <div className="task-steps">
          {steps.map((s, i) => (
            <span key={s} className={i <= step ? "done" : ""}>
              <i>{i < step ? <Check size={10} /> : i + 1}</i>
              {s}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
function NotePage({
  data,
  setData,
  onError,
}: {
  data: LearningNote;
  setData: React.Dispatch<React.SetStateAction<LearningNote | null>>;
  onError: (s: string) => void;
}) {
  const [tab, setTab] = useState<Tab>(
      data.mode === "course" ? "course" : data.format,
    ),
    [editing, setEditing] = useState(false),
    [copyDone, setCopyDone] = useState(false),
    [menu, setMenu] = useState(false),
    [sending, setSending] = useState(false);
  const busy = active(data.job) || sending;
  const canVision =
    data.source.kind === "file"
      ? /\.(mp4|mov|mkv|avi|m4v|webm)$/i.test(data.source.filename || "")
      : data.source.kind === "url" &&
        [
          "douyin.com",
          "bilibili.com",
          "b23.tv",
          "youtube.com",
          "youtu.be",
        ].includes(
          new URL(
            data.source.content || "https://invalid.local",
          ).hostname.replace(/^www\./, ""),
        );
  async function generate(kind: string, args: Record<string, unknown> = {}) {
    setSending(true);
    try {
      await post("/notes/" + data.id + "/generate", { kind, ...args });
      setData(await api("/notes/" + data.id));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSending(false);
    }
  }
  async function progress(value: Progress) {
    try {
      const changes: Record<string, number[] | null> = {};
      for (const key of new Set([
        ...Object.keys(data.progress.answers),
        ...Object.keys(value.answers),
      ])) {
        if (
          JSON.stringify(data.progress.answers[key]) !==
          JSON.stringify(value.answers[key])
        )
          changes[key] = value.answers[key] ?? null;
      }
      const next = await put<LearningNote>("/notes/" + data.id + "/progress", {
        epoch: data.progress.epoch ?? 0,
        answers: changes,
        completed: value.completed.filter(
          (id) => !data.progress.completed.includes(id),
        ),
        ...(value.last_chapter !== data.progress.last_chapter
          ? { last_chapter: value.last_chapter }
          : {}),
      });
      setData((old) =>
        old && (old.id !== next.id || old.updated > next.updated) ? old : next,
      );
    } catch (e) {
      onError("进度未保存：" + (e as Error).message);
      throw e;
    }
  }
  async function copy() {
    try {
      const response = await fetch(
        `/api/notes/${data.id}/export/${tab === "overview" ? "overview" : "markdown"}`,
      );
      if (!response.ok) throw new Error("复制失败，请稍后重试。");
      await navigator.clipboard.writeText(await response.text());
      setCopyDone(true);
      setTimeout(() => setCopyDone(false), 1800);
    } catch (e) {
      onError((e as Error).message);
    }
  }
  const tabs: { id: Tab; label: string; icon: typeof FileText }[] = [
    { id: "overview", label: "一页速览", icon: LayoutGrid },
    { id: "markdown", label: "详细笔记", icon: FileText },
    { id: "poster", label: "长图", icon: Image },
    { id: "mindmap", label: "脑图", icon: Network },
    { id: "course", label: "课程", icon: BookOpen },
    { id: "quiz", label: "测试", icon: BookMarked },
    { id: "source", label: "原文", icon: List },
  ];
  const quiz = data.artifacts.quiz as QuizData | undefined;
  const stale = Object.entries(data.artifact_revisions).some(
    ([key, revision]) =>
      !key.startsWith("archive:") && revision < data.revision,
  );
  return (
    <main className="note-page">
      <div className="note-topline">
        <a className="back-link" href="#library">
          <ArrowLeft size={16} />
          我的笔记
        </a>
        <span className="note-date">
          {date(data.created)} · 版本 {data.revision || "待生成"}
        </span>
        <div className="row">
          <button
            className="icon-button"
            aria-label="复制 Markdown"
            disabled={!data.note}
            onClick={copy}
          >
            {copyDone ? <Check size={18} /> : <Copy size={18} />}
          </button>
          <button
            className="button secondary"
            disabled={!data.note || busy}
            onClick={() => setEditing((v) => !v)}
          >
            <Pencil size={15} />
            编辑笔记
          </button>
          <div className="export-menu">
            <button
              className="button primary"
              disabled={!data.note}
              onClick={() => setMenu((v) => !v)}
            >
              <ArrowDownToLine size={16} />
              导出
              <ChevronDown size={13} />
            </button>
            {menu && (
              <div className="dropdown">
                {[
                  { kind: "markdown", name: "完整笔记 · Markdown" },
                  { kind: "overview", name: "一页速览 · Markdown" },
                  { kind: "outline", name: "脑图大纲 · Markdown" },
                ].map((f) => (
                  <a
                    key={f.kind}
                    href={`/api/notes/${data.id}/export/${f.kind}`}
                    onClick={() => setMenu(false)}
                  >
                    {f.name}
                  </a>
                ))}
                <button
                  onClick={() => {
                    setTab("poster");
                    setMenu(false);
                  }}
                >
                  长图 · PNG / 分图 ZIP
                </button>
                <button
                  onClick={() => {
                    setTab("mindmap");
                    setMenu(false);
                  }}
                >
                  脑图 · SVG / PNG
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      {data.job && (
        <TaskBanner
          job={data.job}
          onCancel={async () => {
            try {
              await post("/jobs/" + data.job!.id + "/cancel");
              setData(await api("/notes/" + data.id));
            } catch (e) {
              onError((e as Error).message);
            }
          }}
          onRetry={async () => {
            try {
              await post("/jobs/" + data.job!.id + "/retry");
              setData(await api("/notes/" + data.id));
            } catch (e) {
              onError((e as Error).message);
            }
          }}
        />
      )}
      {data.note ? (
        <>
          <div className="note-subheading">
            <span>
              {data.source.kind === "url"
                ? "链接笔记"
                : data.source.kind === "file"
                  ? "文件笔记"
                  : "正文笔记"}
            </span>
            <span>{data.scope}</span>
          </div>
          <nav className="result-tabs" aria-label="学习形式">
            {tabs.map((t) => (
              <button
                key={t.id}
                className={tab === t.id ? "active" : ""}
                onClick={() => {
                  setTab(t.id);
                  setEditing(false);
                }}
              >
                <t.icon size={16} />
                {t.label}
              </button>
            ))}
          </nav>
          {stale && (
            <div className="stale-notice">
              笔记已更新。已有课程与测试保留原版本的学习记录；可重新生成以更新内容。
              <button
                disabled={busy}
                onClick={() => generate(tab === "quiz" ? "quiz" : "course")}
              >
                重新生成{tab === "quiz" ? "测试" : "课程"}
              </button>
            </div>
          )}
          {data.warnings.length > 0 && (
            <details className="source-warnings">
              <summary>材料识别说明 · {data.warnings.length} 项</summary>
              <ul>
                {data.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </details>
          )}
          {editing ? (
            <Editor
              data={data}
              onSaved={setData}
              onClose={() => setEditing(false)}
              onError={onError}
            />
          ) : (
            <Suspense
              fallback={
                <div className="loading-view">
                  <Loader2 className="spin" />
                  正在打开…
                </div>
              }
            >
              {tab === "overview" || tab === "markdown" ? (
                <Reading data={data} overview={tab === "overview"} />
              ) : tab === "poster" ? (
                <Poster data={data} onError={onError} />
              ) : tab === "mindmap" ? (
                <Mindmap data={data} onError={onError} />
              ) : tab === "course" ? (
                <CourseView
                  data={data}
                  generate={generate}
                  onProgress={progress}
                  busy={busy}
                />
              ) : tab === "quiz" ? (
                quiz ? (
                  <Quiz quiz={quiz} data={data} onProgress={progress} />
                ) : (
                  <GenerateEmpty
                    icon="quiz"
                    title="检验一下，是否真的学会"
                    description="根据这份材料出题，每道题都有解释。答完后，回到没掌握的知识点。"
                    button="生成测试题"
                    busy={busy}
                    onClick={() => generate("quiz")}
                  />
                )
              ) : (
                <Original data={data} />
              )}
            </Suspense>
          )}
          <LearningHistory data={data} onError={onError} />
          <div className="note-bottom">
            <span>同一份材料，不同的学习方式。</span>
            <button
              className="text-button"
              disabled={busy}
              onClick={() => generate("summary")}
            >
              <Sparkles size={14} />
              重新整理笔记
            </button>
            {canVision && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => generate("vision")}
              >
                <Image size={14} />
                补充视频画面分析
              </button>
            )}
          </div>
        </>
      ) : (
        <div className="processing-empty">
          <div className="floating-book">
            <NotebookPen size={45} strokeWidth={1.2} />
          </div>
          <h1>{data.title}</h1>
          <p>
            {active(data.job)
              ? "先理解材料，再把值得留下的知识整理出来。"
              : "材料尚未完成整理，请查看上方的处理说明。"}
          </p>
          <span>正文提取完成后会保留，重试时无需重新上传。</span>
          {!busy && (
            <div className="row centered retry-alternatives">
              <a className="button secondary" href="#new/file">
                改为上传文件
              </a>
              <a className="button secondary" href="#new/text">
                改为粘贴文稿
              </a>
              {data.source.kind === "url" && (
                <a className="text-button" href="#settings">
                  配置平台访问授权
                </a>
              )}
            </div>
          )}
          {canVision && !busy && (
            <button
              className="button secondary"
              onClick={() => generate("vision")}
            >
              尝试分析视频画面
            </button>
          )}
          {data.segments.length > 0 && (
            <button
              className="button secondary"
              onClick={() => setTab("source")}
            >
              查看已提取原文
            </button>
          )}
          {tab === "source" && <Original data={data} />}
        </div>
      )}
    </main>
  );
}
export default function App() {
  const hash = useHash(),
    id = hash.startsWith("#note/") ? hash.slice(6) : null;
  const [notes, setNotes] = useState<NoteCard[]>([]),
    [data, setData] = useState<LearningNote | null>(null),
    [settings, setSettings] = useState<Settings | null>(null),
    [error, setError] = useState(""),
    [search, setSearch] = useState(""),
    [loading, setLoading] = useState(false);
  const refresh = useCallback(() => {
    api<NoteCard[]>("/notes")
      .then(setNotes)
      .catch((e) => setError(e.message));
  }, []);
  const refreshSettings = useCallback(() => {
    api<Settings>("/settings")
      .then(setSettings)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    refresh();
    refreshSettings();
  }, [refresh, refreshSettings]);
  useEffect(() => {
    if (!id) {
      setData(null);
      refresh();
      return;
    }
    let alive = true;
    setData(null);
    setLoading(true);
    api<LearningNote>("/notes/" + id)
      .then((n) => {
        if (alive) {
          setData(n);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (alive) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [id, refresh]);
  useEffect(() => {
    if (!id) return;
    let alive = true;
    const timer = setInterval(() => {
      api<LearningNote>("/notes/" + id)
        .then((next) => {
          if (alive)
            setData((old) =>
              old &&
              (old.updated > next.updated ||
                (old.updated === next.updated &&
                  (old.job?.updated ?? 0) >= (next.job?.updated ?? 0)))
                ? old
                : next,
            );
        })
        .catch(() => {});
    }, 2200);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);
  useEffect(() => {
    if (id || !notes.some((n) => active(n.job))) return;
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [notes, id, refresh]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [hash]);
  const open = (noteId: string) => {
    location.hash = "note/" + noteId;
  };
  return (
    <>
      <header className="site-header">
        <div className="header-inner">
          <Logo />
          <nav className="main-nav">
            <a href="#" className={!hash ? "active" : ""}>
              <Plus size={16} />
              新建笔记
            </a>
            <a href="#library" className={hash === "#library" ? "active" : ""}>
              <FolderOpen size={16} />
              笔记库
            </a>
          </nav>
          <div className="header-right">
            <Status settings={settings} />
            <a href="#settings" className="settings-link" aria-label="设置">
              <Settings2 size={18} />
            </a>
            <span className="local-avatar">本地</span>
          </div>
        </div>
      </header>
      {error && (
        <div className="toast" role="alert">
          <span>{error}</span>
          <button aria-label="关闭提示" onClick={() => setError("")}>
            <X size={17} />
          </button>
        </div>
      )}
      {hash === "#settings" ? (
        <SettingsPage
          settings={settings}
          onRefresh={refreshSettings}
          onError={setError}
        />
      ) : id ? (
        loading ? (
          <div className="loading-view">
            <Loader2 className="spin" />
            正在打开笔记…
          </div>
        ) : !data || data.id !== id ? (
          <div className="loading-view">
            <p>这份笔记暂时无法打开，请检查服务或返回笔记库。</p>
            <a href="#library" className="button secondary">
              返回笔记库
            </a>
          </div>
        ) : (
          <NotePage key={id} data={data} setData={setData} onError={setError} />
        )
      ) : hash === "#library" ? (
        <main className="library-page">
          <div className="section-heading">
            <div>
              <span className="eyebrow">知识，慢慢积累</span>
              <h1>我的笔记库</h1>
              <p>{notes.length} 份材料，随时回来接着学。</p>
            </div>
            <a className="button primary" href="#">
              <Plus size={16} />
              新建笔记
            </a>
          </div>
          <div className="library-search">
            <Search size={18} />
            <input
              aria-label="搜索笔记"
              placeholder="搜索笔记标题…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <NoteList
            notes={notes.filter((n) =>
              n.title.toLowerCase().includes(search.toLowerCase()),
            )}
            onOpen={open}
          />
        </main>
      ) : null}
      <div hidden={!!id || hash === "#settings" || hash === "#library"}>
        <Home
          notes={notes}
          settings={settings}
          onImported={open}
          onRefresh={refresh}
          onError={setError}
        />
      </div>
      <footer className="site-footer">
        <span>拾页</span>
        <span>少一点整理，多一点理解。</span>
        <span>
          <AudioLines size={13} />
          本地学习空间
        </span>
      </footer>
    </>
  );
}
