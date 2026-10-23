import { useState } from "react";
import { api, date } from "./api";
import {
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Flag,
  RotateCcw,
  Sparkles,
  Trophy,
} from "lucide-react";
import type {
  Chapter,
  Course,
  LearningNote,
  Lesson,
  Progress,
  Question,
  QuizData,
} from "./types";
import { displayText, Markdown } from "./Reading";

type Generate = (kind: string, args?: Record<string, unknown>) => Promise<void>;
function QuestionCard({
  question,
  answer,
  onAnswer,
  index,
}: {
  question: Question;
  answer: number[] | undefined;
  onAnswer: (id: string, value: number[]) => Promise<void>;
  index: number;
}) {
  const [choice, setChoice] = useState<number[]>(answer || []),
    [saving, setSaving] = useState(false);
  const submitted = answer !== undefined,
    correct =
      submitted &&
      JSON.stringify([...answer].sort()) ===
        JSON.stringify([...question.correct].sort());
  function select(index: number) {
    if (submitted) return;
    setChoice((old) =>
      question.kind === "multiple"
        ? old.includes(index)
          ? old.filter((v) => v !== index)
          : [...old, index]
        : [index],
    );
  }
  async function submit() {
    setSaving(true);
    try {
      await onAnswer(question.id, choice);
    } catch {
      // Parent shows the save error; keep the choice available for retry.
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="question-card">
      <div className="row spread">
        <span className="question-number">第 {index + 1} 题</span>
        <span className="tag">
          {question.kind === "multiple"
            ? "多选题"
            : question.kind === "boolean"
              ? "判断题"
              : "单选题"}
        </span>
      </div>
      <div className="question-prompt">
        <Markdown>{question.prompt}</Markdown>
      </div>
      <div className="options">
        {question.options.map((label, i) => (
          <button
            key={i}
            disabled={submitted}
            onClick={() => select(i)}
            className={
              "option " +
              (choice.includes(i) ? "chosen " : "") +
              (submitted && question.correct.includes(i)
                ? "correct "
                : submitted && choice.includes(i)
                  ? "wrong "
                  : "")
            }
          >
            <span className="option-letter">{String.fromCharCode(65 + i)}</span>
            <span>{label}</span>
            {submitted && question.correct.includes(i) && (
              <CheckCircle2 size={18} />
            )}
          </button>
        ))}
      </div>
      {submitted ? (
        <div className={"answer-box " + (correct ? "right" : "")}>
          <strong>{correct ? "答对了，继续保持" : "再看一遍这个知识点"}</strong>
          <p>{displayText(question.explanation)}</p>
        </div>
      ) : (
        <button
          className="button primary"
          disabled={!choice.length || saving}
          onClick={submit}
        >
          {saving ? "正在保存…" : "确认答案"}
        </button>
      )}
    </section>
  );
}
export function Quiz({
  quiz,
  data,
  onProgress,
}: {
  quiz: QuizData;
  data: LearningNote;
  onProgress: (p: Progress) => Promise<void>;
}) {
  const [resetting, setResetting] = useState(false),
    [attempt, setAttempt] = useState(0);
  const answers = data.progress.answers;
  const done = quiz.questions.filter((q) => answers[q.id] !== undefined);
  const correct = done.filter(
    (q) =>
      JSON.stringify([...answers[q.id]].sort()) ===
      JSON.stringify([...q.correct].sort()),
  );
  async function reset(onlyWrong: boolean) {
    setResetting(true);
    try {
      const updated = { ...answers };
      quiz.questions.forEach((q) => {
        if (!onlyWrong || !correct.includes(q)) delete updated[q.id];
      });
      await onProgress({ ...data.progress, answers: updated });
      setAttempt((v) => v + 1);
    } catch {
      // Parent shows the error without discarding answers.
    } finally {
      setResetting(false);
    }
  }
  return (
    <div className="quiz-page">
      <header className="quiz-header">
        <span className="eyebrow">检验理解，而不只是记住</span>
        <h1>{quiz.title}</h1>
        <div className="row spread">
          <span>
            已完成 {done.length} / {quiz.questions.length} 题
          </span>
          <span>答对 {correct.length} 题</span>
        </div>
        <div className="progress-track">
          <i
            style={{ width: (done.length / quiz.questions.length) * 100 + "%" }}
          />
        </div>
      </header>
      {done.length === quiz.questions.length && (
        <div className="quiz-result">
          <Trophy size={30} />
          <div>
            <h2>这一轮，学到了哪里？</h2>
            <p>
              正确率{" "}
              {Math.round((correct.length / quiz.questions.length) * 100)}%。
              {correct.length === quiz.questions.length
                ? "所有知识点都答对了。"
                : "对照原文，把没掌握的地方再过一遍。"}
            </p>
          </div>
          <button
            className="button secondary"
            disabled={resetting}
            onClick={() => reset(true)}
          >
            <RotateCcw size={15} />
            重做错题
          </button>
          <button
            className="text-button"
            disabled={resetting}
            onClick={() => reset(false)}
          >
            全部重做
          </button>
        </div>
      )}
      {quiz.questions.map((q, i) => (
        <QuestionCard
          key={JSON.stringify([q, attempt, answers[q.id]])}
          question={q}
          index={i}
          answer={answers[q.id]}
          onAnswer={(id, value) =>
            onProgress({
              ...data.progress,
              answers: { ...data.progress.answers, [id]: value },
            })
          }
        />
      ))}
    </div>
  );
}
export function GenerateEmpty({
  icon,
  title,
  description,
  button,
  busy,
  onClick,
}: {
  icon?: "course" | "quiz";
  title: string;
  description: string;
  button: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <div className="generate-empty">
      <div className="empty-illustration">
        {icon === "course" ? <BookOpen size={34} /> : <Sparkles size={34} />}
      </div>
      <h2>{title}</h2>
      <Markdown>{description}</Markdown>
      <button className="button primary" disabled={busy} onClick={onClick}>
        {busy ? <span className="spinner" /> : <Sparkles size={16} />}{" "}
        {busy ? "正在准备…" : button}
      </button>
      <span className="empty-caption">由所选模型按原始材料生成 · 按需准备</span>
    </div>
  );
}
export function CourseView({
  data,
  generate,
  onProgress,
  busy,
}: {
  data: LearningNote;
  generate: Generate;
  onProgress: (p: Progress) => Promise<void>;
  busy: boolean;
}) {
  const course = data.artifacts.course as Course | undefined;
  const [current, setCurrent] = useState(data.progress.last_chapter || ""),
    [saving, setSaving] = useState(false);
  if (!course)
    return (
      <GenerateEmpty
        icon="course"
        title="把这份材料，一节一节学明白"
        description="从基础概念到实际应用，按知识结构拆成一条清晰的学习路径。每节都有讲解和练习，学习进度自动保存。"
        button="生成学习路径"
        busy={busy}
        onClick={() => generate("course")}
      />
    );
  const validCurrent =
    current === "quiz" ||
    course.chapters.some((c) => c.id === current) ||
    course.chapters.some(
      (_, i) =>
        i < course.chapters.length - 1 &&
        (i + 1) % 3 === 0 &&
        current === "stage:" + (i + 1),
    );
  const selected = validCurrent ? current : course.chapters[0].id,
    chapter = course.chapters.find((c) => c.id === selected);
  const lesson = data.artifacts["lesson:" + selected] as Lesson | undefined;
  const stage = selected.startsWith("stage:")
    ? (data.artifacts[selected] as QuizData | undefined)
    : undefined;
  const final =
    selected === "quiz"
      ? (data.artifacts.quiz as QuizData | undefined)
      : undefined;
  async function selectChapter(c: Chapter) {
    setCurrent(c.id);
    try {
      await onProgress({ ...data.progress, last_chapter: c.id });
    } catch {
      /* Parent reports save failure. */
    }
  }
  async function complete() {
    if (!chapter) return;
    setSaving(true);
    try {
      const i = course!.chapters.findIndex((c) => c.id === chapter.id);
      await onProgress({
        ...data.progress,
        completed: [...new Set([...data.progress.completed, chapter.id])],
        last_chapter:
          course!.chapters[Math.min(i + 1, course!.chapters.length - 1)].id,
      });
      if (i === course!.chapters.length - 1) setCurrent("quiz");
      else if ((i + 1) % 3 === 0) setCurrent("stage:" + (i + 1));
      else setCurrent(course!.chapters[i + 1].id);
    } catch {
      // Parent shows the save error; keep the choice available for retry.
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="course-layout">
      <aside className="course-sidebar">
        <span className="eyebrow">你的学习路径</span>
        <h2>{course.title}</h2>
        <p>
          {data.progress.completed.length} / {course.chapters.length} 节已完成
        </p>
        <div className="progress-track">
          <i
            style={{
              width:
                (data.progress.completed.length / course.chapters.length) *
                  100 +
                "%",
            }}
          />
        </div>
        <nav>
          {course.chapters.map((c, i) => (
            <div key={c.id}>
              <button
                className={
                  "chapter-button " + (selected === c.id ? "active" : "")
                }
                onClick={() => selectChapter(c)}
              >
                {data.progress.completed.includes(c.id) ? (
                  <CheckCircle2 size={19} />
                ) : (
                  <span className="chapter-count">{i + 1}</span>
                )}
                <span>{c.title}</span>
              </button>
              {(i + 1) % 3 === 0 && i < course.chapters.length - 1 && (
                <button
                  className={
                    "chapter-button stage " +
                    (selected === "stage:" + (i + 1) ? "active" : "")
                  }
                  onClick={() => setCurrent("stage:" + (i + 1))}
                >
                  <Flag size={17} />
                  <span>阶段测验 · 前 {i + 1} 节</span>
                </button>
              )}
            </div>
          ))}
          <button
            className={
              "chapter-button stage " + (selected === "quiz" ? "active" : "")
            }
            onClick={() => setCurrent("quiz")}
          >
            <Trophy size={18} />
            <span>最终测试</span>
          </button>
        </nav>
      </aside>
      <div className="lesson-content">
        {chapter ? (
          lesson ? (
            <article className="lesson-paper">
              <span className="eyebrow">
                第 {course.chapters.findIndex((c) => c.id === chapter.id) + 1}{" "}
                节
              </span>
              <h1>{lesson.title}</h1>
              <div className="lesson-objective">
                <BookOpen size={18} />
                <p>{displayText(lesson.objective)}</p>
              </div>
              <Markdown>{lesson.markdown}</Markdown>
              <div className="conclusion">
                <span>这一节，记住什么</span>
                <p>{displayText(lesson.summary)}</p>
              </div>
              <h2>随堂练习</h2>
              <Quiz
                quiz={{
                  title: "检验这一节的理解",
                  questions: lesson.questions,
                }}
                data={data}
                onProgress={onProgress}
              />
              <button
                className="button primary complete-button"
                disabled={saving}
                onClick={complete}
              >
                {data.progress.completed.includes(chapter.id) ? (
                  <Check size={17} />
                ) : (
                  <Circle size={17} />
                )}
                标记学完，继续下一步
                <ChevronRight size={17} />
              </button>
            </article>
          ) : (
            <GenerateEmpty
              icon="course"
              title={chapter.title}
              description={chapter.objective}
              button="准备这一节"
              busy={busy}
              onClick={() => generate("lesson", { chapter_id: chapter.id })}
            />
          )
        ) : stage || final ? (
          <Quiz quiz={(stage || final)!} data={data} onProgress={onProgress} />
        ) : (
          <GenerateEmpty
            icon="quiz"
            title={
              selected === "quiz"
                ? "最后，用测试检查理解"
                : "停一下，检验这一阶段"
            }
            description="每道题都有解析。答错的知识点可以再练一次。"
            button="生成测验"
            busy={busy}
            onClick={() =>
              selected === "quiz"
                ? generate("quiz")
                : generate("stage", {
                    boundary: Number(selected.split(":")[1]),
                  })
            }
          />
        )}
      </div>
    </div>
  );
}

type HistoryEntry = {
  id: string;
  key: string;
  revision: number;
  created: number;
  content: Course | Lesson | QuizData;
  progress: Progress;
};
export function LearningHistory({
  data,
  onError,
}: {
  data: LearningNote;
  onError: (s: string) => void;
}) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]),
    [loaded, setLoaded] = useState(false),
    [selected, setSelected] = useState<HistoryEntry | null>(null);
  async function load() {
    try {
      setEntries(await api("/notes/" + data.id + "/learning-history"));
      setLoaded(true);
    } catch (e) {
      onError((e as Error).message);
    }
  }
  return (
    <details
      className="learning-history"
      onToggle={(e) => {
        if (e.currentTarget.open) load();
      }}
    >
      <summary>历史课程与答题记录</summary>
      {loaded && !entries.length ? (
        <p>重新生成课程或测验后，旧内容与当时的学习记录会保留在这里。</p>
      ) : (
        <div className="history-list">
          {entries.map((entry) => (
            <button
              key={entry.id}
              className={selected?.id === entry.id ? "selected" : ""}
              onClick={() => setSelected(entry)}
            >
              {entry.content.title} · 笔记版本 {entry.revision} ·{" "}
              {date(entry.created)}
            </button>
          ))}
        </div>
      )}
      {selected && (
        <div className="history-preview">
          <div className="row spread">
            <strong>{selected.content.title}</strong>
            <span>历史只读记录</span>
          </div>
          {"chapters" in selected.content ? (
            <ol>
              {selected.content.chapters.map((c) => (
                <li key={c.id}>
                  {c.title}
                  {selected.progress.completed.includes(c.id)
                    ? "（当时已学完）"
                    : ""}
                </li>
              ))}
            </ol>
          ) : "markdown" in selected.content ? (
            <Markdown>{selected.content.markdown}</Markdown>
          ) : null}
          {"questions" in selected.content &&
            selected.content.questions.map((q) => (
              <details key={q.id}>
                <summary>{q.prompt}</summary>
                <p>
                  当时的选择：
                  {selected.progress.answers[q.id]
                    ?.map((i) => q.options[i])
                    .join("、") || "未作答"}
                </p>
                <p>正确答案：{q.correct.map((i) => q.options[i]).join("、")}</p>
                <p>{q.explanation}</p>
              </details>
            ))}
        </div>
      )}
    </details>
  );
}
