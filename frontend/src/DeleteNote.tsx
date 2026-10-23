import { useEffect, useRef, useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { api, post } from "./api";
import type { Job } from "./types";

type DeleteInfo = {
  id: string;
  title: string;
  active_job: Pick<Job, "id" | "status" | "stage"> | null;
};

export function DeleteNote({
  id,
  title,
  onClose,
  onDeleted,
}: {
  id: string;
  title: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [info, setInfo] = useState<DeleteInfo | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  function dismiss() {
    if (busy) return;
    dialog.current?.close();
    onClose();
  }
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  useEffect(() => {
    let alive = true;
    async function refresh() {
      try {
        const next = await api<DeleteInfo>(`/notes/${id}/delete-info`);
        if (alive) setInfo(next);
      } catch (e) {
        if (alive) {
          setInfo(null);
          setError((e as Error).message);
        }
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 1500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);
  async function stop() {
    if (!info?.active_job || busy) return;
    setBusy("stop");
    setError("");
    try {
      await post(`/jobs/${info.active_job.id}/cancel`);
      setInfo(await api<DeleteInfo>(`/notes/${id}/delete-info`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function remove() {
    if (!info || info.active_job || busy) return;
    setBusy("delete");
    setError("");
    try {
      await api(`/notes/${id}`, { method: "DELETE" });
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
      setBusy("");
    }
  }
  const stopping =
    !!info?.active_job &&
    ["pausing", "cancelling"].includes(info.active_job.status);
  return (
    <dialog
      ref={dialog}
      className="delete-dialog"
      aria-labelledby="delete-note-title"
      aria-describedby="delete-note-scope"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
    >
      <span className="delete-dialog-icon">
        <Trash2 size={23} />
      </span>
      <h2 id="delete-note-title">删除这份笔记？</h2>
      <p className="delete-note-name">{info?.title || title}</p>
      <p id="delete-note-scope">
        将永久删除这份笔记的全部版本、课程与答题历史、任务记录，
        以及拾页资料库中的原材料副本、处理缓存和导出文件。
      </p>
      <p className="delete-warning">
        删除后无法恢复。电脑其他位置的原始文件、已下载的文件和备份仍由你管理。
      </p>
      {!info && !error && <p role="status">正在确认任务状态…</p>}
      {info?.active_job && (
        <div className="delete-active-task" role="status">
          <strong>请先停止当前任务</strong>
          <p>{info.active_job.stage}。处理完全停止后，才可确认删除。</p>
          <button
            className="button secondary"
            disabled={!!busy || stopping}
            onClick={() => void stop()}
          >
            {stopping || busy === "stop" ? (
              <>
                <Loader2 size={15} className="spin" />
                正在等待处理停止…
              </>
            ) : (
              "停止这份笔记的任务"
            )}
          </button>
        </div>
      )}
      {error && (
        <p className="delete-error" role="alert">
          {error}
        </p>
      )}
      <div className="delete-dialog-actions">
        <button
          className="button secondary"
          autoFocus
          disabled={!!busy}
          onClick={dismiss}
        >
          取消
        </button>
        <button
          className="button danger"
          disabled={!!busy || !info || !!info.active_job}
          onClick={() => void remove()}
        >
          {busy === "delete" ? (
            <Loader2 size={16} className="spin" />
          ) : (
            <Trash2 size={16} />
          )}
          {busy === "delete" ? "正在删除…" : "确认永久删除"}
        </button>
      </div>
    </dialog>
  );
}
