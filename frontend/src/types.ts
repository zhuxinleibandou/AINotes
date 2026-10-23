export type Format = "poster" | "markdown" | "mindmap";
export type Segment = {
  id: string;
  text: string;
  location: string;
  start: number | null;
  end: number | null;
};
export type Section = {
  title: string;
  kind: "concept" | "steps" | "case" | "comparison" | "process" | "warning";
  markdown: string;
  keypoints: string[];
  source_ids: string[];
};
export type Content = {
  title: string;
  subtitle: string;
  overview: string;
  sections: Section[];
  limitations: string[];
  conclusion: string;
};
export type Question = {
  id: string;
  kind: "single" | "multiple" | "boolean";
  prompt: string;
  options: string[];
  correct: number[];
  explanation: string;
  source_ids: string[];
};
export type QuizData = { title: string; questions: Question[] };
export type Chapter = {
  id: string;
  title: string;
  objective: string;
  source_ids: string[];
};
export type Course = {
  title: string;
  description: string;
  chapters: Chapter[];
};
export type Lesson = {
  title: string;
  objective: string;
  markdown: string;
  summary: string;
  source_ids: string[];
  questions: Question[];
};
export type Progress = {
  epoch?: number;
  completed: string[];
  answers: Record<string, number[]>;
  last_chapter: string;
};
export type Job = {
  id: string;
  note_id: string;
  kind: string;
  status:
    | "queued"
    | "running"
    | "pausing"
    | "paused"
    | "cancelling"
    | "completed"
    | "failed"
    | "cancelled"
    | "interrupted";
  stage: string;
  error: string;
  created: number;
  updated: number;
};
export type Source = {
  kind: "text" | "url" | "file";
  content?: string;
  filename?: string;
  size?: number;
};
export type LearningNote = {
  id: string;
  title: string;
  source: Source;
  instructions: string;
  format: Format;
  mode: string;
  segments: Segment[];
  scope: string;
  warnings: string[];
  note: Content | null;
  revision: number;
  created: number;
  updated: number;
  artifacts: Record<string, unknown>;
  artifact_revisions: Record<string, number>;
  progress: Progress;
  job: Job | null;
};
export type NoteCard = Pick<
  LearningNote,
  | "id"
  | "title"
  | "source"
  | "scope"
  | "revision"
  | "created"
  | "updated"
  | "format"
  | "progress"
  | "job"
> & { ready: boolean; subtitle: string };
export type Provider =
  | "deepseek"
  | "moonshot"
  | "kimi_code"
  | "glm"
  | "custom"
  | "ollama"
  | "lmstudio"
  | "local_custom";
export type ModelProfile = {
  base_url: string;
  model: string;
  api_key?: string;
  clear_api_key?: boolean;
  api_key_configured: boolean;
  supports_images: boolean;
  output_format: "json_object" | "json_schema" | "prompt";
  max_tokens: number;
  context_chars: number;
  reasoning_effort: string;
};
export type ProviderPreset = {
  label: string;
  local: boolean;
  base_url: string;
  model: string;
  models: string[];
  docs: string;
};
export type Settings = {
  active_tasks: {
    id: string;
    note_id: string;
    title: string;
    status: Job["status"];
    stage: string;
  }[];
  paused_tasks: number;
  generation_backend: "codex" | "api" | "local";
  api_provider: Provider;
  local_provider: Provider;
  providers: Record<Provider, ModelProfile>;
  provider_presets: Record<Provider, ProviderPreset>;
  whisper_model: string;
  model: string;
  default_model: string;
  codex_available: boolean;
  codex_logged_in: boolean;
  storage: string;
  free_gb: number;
  ffmpeg: boolean;
  ocr: boolean;
  transcription: string;
  upload_limit_mb: number;
  platform_cookies: Record<string, boolean>;
};
