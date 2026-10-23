import { useCallback, useEffect, useState } from "react";
import {
  Check,
  Cloud,
  Download,
  HardDrive,
  Loader2,
  Settings2,
  Terminal,
} from "lucide-react";
import { api, post, put } from "./api";
import type { Settings, ModelProfile, Provider } from "./types";

export function ModelSettings({
  settings,
  onRefresh,
  onError,
}: {
  settings: Settings | null;
  onRefresh: () => void;
  onError: (message: string) => void;
}) {
  const [backend, setBackend] =
    useState<Settings["generation_backend"]>("codex");
  const [apiProvider, setApiProvider] = useState<Provider>("deepseek");
  const [localProvider, setLocalProvider] = useState<Provider>("ollama");
  const [profiles, setProfiles] = useState<
    Partial<Record<Provider, ModelProfile>>
  >({});
  const [codexModel, setCodexModel] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(
    null,
  );
  const [modelLists, setModelLists] = useState<
    Partial<Record<Provider, string[]>>
  >({});
  type Tasks = Pick<Settings, "active_tasks" | "paused_tasks">;
  const [tasks, setTasks] = useState<Tasks | null>(null);
  const loadTasks = useCallback(async () => {
    try {
      setTasks(await api<Tasks>("/settings/tasks"));
    } catch {
      setTasks(null);
    }
  }, []);
  useEffect(() => {
    void loadTasks();
    const timer = setInterval(() => void loadTasks(), 2000);
    return () => clearInterval(timer);
  }, [loadTasks]);
  const locked = tasks === null || tasks.active_tasks.length > 0;
  const disabled = !!busy || locked;
  useEffect(() => {
    onRefresh();
  }, [locked, onRefresh]);
  // Task-status polling must never discard unsaved edits or a pasted key.
  const savedConfig = JSON.stringify(
    settings && {
      generation_backend: settings.generation_backend,
      api_provider: settings.api_provider,
      local_provider: settings.local_provider,
      providers: settings.providers,
      model: settings.model,
    },
  );
  useEffect(() => {
    if (!savedConfig || savedConfig === "null") return;
    const config = JSON.parse(savedConfig);
    setBackend(config.generation_backend || "codex");
    setApiProvider(config.api_provider || "deepseek");
    setLocalProvider(config.local_provider || "ollama");
    setProfiles(config.providers || {});
    setCodexModel(config.model || "");
  }, [savedConfig]);
  const provider = backend === "local" ? localProvider : apiProvider;
  const profile = profiles[provider];
  const preset = settings?.provider_presets?.[provider];
  const availableModels = modelLists[provider] ?? preset?.models ?? [];
  function changed() {
    setSaved(false);
    setResult(null);
  }
  function update(patch: Partial<ModelProfile>) {
    setProfiles((old) => ({
      ...old,
      [provider]: { ...old[provider]!, ...patch },
    }));
    if (patch.base_url !== undefined || patch.api_key !== undefined)
      setModelLists((old) => ({ ...old, [provider]: undefined }));
    changed();
  }
  function wire(value: ModelProfile) {
    const { api_key_configured, ...fields } = value;
    void api_key_configured;
    return fields;
  }
  async function save() {
    if (!settings || disabled) return;
    setBusy("save");
    try {
      await put("/settings", {
        whisper_model: settings.whisper_model,
        model: codexModel,
        generation_backend: backend,
        api_provider: apiProvider,
        local_provider: localProvider,
        providers: Object.fromEntries(
          Object.entries(profiles).map(([id, p]) => [id, wire(p)]),
        ),
      });
      setProfiles((old) =>
        Object.fromEntries(
          Object.entries(old).map(([id, p]) => [
            id,
            { ...p, api_key: "", clear_api_key: false },
          ]),
        ),
      );
      setSaved(true);
      onRefresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function connect(action: "models" | "test-model") {
    if (!profile || disabled) return;
    setBusy(action);
    setResult(null);
    try {
      const value = await post<{ models?: string[]; message?: string }>(
        "/settings/" + action,
        { provider, profile: wire(profile) },
      );
      if (action === "models") {
        setModelLists((old) => ({ ...old, [provider]: value.models || [] }));
        setResult({
          ok: true,
          message: value.models?.length
            ? `已读取 ${value.models.length} 个模型，可在模型列表中选择。`
            : "服务未返回模型列表，可手动填写模型ID。",
        });
      } else setResult({ ok: true, message: value.message || "测试完成。" });
    } catch (e) {
      setResult({ ok: false, message: (e as Error).message });
    } finally {
      setBusy("");
    }
  }
  async function taskAction(action: "pause" | "resume") {
    setBusy(action);
    try {
      await post(
        "/settings/" + (action === "pause" ? "pause-tasks" : "resume-tasks"),
        {},
      );
      await loadTasks();
      onRefresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  if (!settings?.provider_presets)
    return (
      <section className="settings-card">
        <h2>模型设置</h2>
        <p>正在读取模型设置；更新后请先重新启动拾页。</p>
      </section>
    );
  return (
    <section className="settings-card model-settings">
      <h2>选择生成方式</h2>
      <p>
        总结、课程、测试统一使用这里的选择。有任务在处理时，请先暂停，待完全停止后再切换模型。
      </p>
      {locked && (
        <div className="model-task-notice" role="status">
          <strong>
            {tasks
              ? "先暂停任务，再切换模型"
              : "正在确认任务状态，暂不能切换模型"}
          </strong>
          {tasks && (
            <>
              <p>
                {tasks.active_tasks.length}{" "}
                个任务正在处理或等待处理。已解析的材料和已完成内容会保留，未完成的生成需要重新开始。
              </p>
              <ul>
                {tasks.active_tasks.slice(0, 3).map((task) => (
                  <li key={task.id}>
                    {task.title} · {task.stage}
                  </li>
                ))}
              </ul>
              <button
                className="button secondary"
                disabled={
                  !!busy ||
                  tasks.active_tasks.every((task) =>
                    ["pausing", "cancelling"].includes(task.status),
                  )
                }
                onClick={() => void taskAction("pause")}
              >
                {busy === "pause" ||
                tasks.active_tasks.every((task) =>
                  ["pausing", "cancelling"].includes(task.status),
                )
                  ? "正在等待任务停止…"
                  : "暂停任务后切换"}
              </button>
            </>
          )}
        </div>
      )}
      {!locked && !!tasks?.paused_tasks && (
        <div className="model-task-notice" role="status">
          <strong>任务已暂停，可以切换模型</strong>
          <p>
            {tasks.paused_tasks}{" "}
            个任务等待继续。保存模型设置后，可点击下方按钮，使用已保存的模型继续处理。
          </p>
          <button
            className="button secondary"
            disabled={disabled}
            onClick={() => void taskAction("resume")}
          >
            继续已暂停的任务
          </button>
        </div>
      )}
      <div className="model-mode-grid" role="group" aria-label="生成方式">
        {(
          [
            {
              id: "codex",
              icon: Terminal,
              title: "本机 Codex",
              detail: "沿用已有登录",
            },
            {
              id: "api",
              icon: Cloud,
              title: "模型 API",
              detail: "DeepSeek、Kimi、GLM 等",
            },
            {
              id: "local",
              icon: HardDrive,
              title: "本地模型",
              detail: "Ollama / LM Studio",
            },
          ] as const
        ).map((item) => (
          <button
            key={item.id}
            aria-pressed={backend === item.id}
            disabled={disabled}
            onClick={() => {
              setBackend(item.id);
              changed();
            }}
          >
            <item.icon size={21} />
            <strong>{item.title}</strong>
            <span>{item.detail}</span>
          </button>
        ))}
      </div>
      {backend === "codex" ? (
        <>
          <label>
            Codex 生成模型
            <input
              value={codexModel}
              placeholder={"留空沿用：" + settings.default_model}
              disabled={disabled}
              onChange={(e) => {
                setCodexModel(e.target.value);
                changed();
              }}
            />
          </label>
          <small>使用本机 Codex 登录与思考程度配置，生成需要联网。</small>
        </>
      ) : profile && preset ? (
        <>
          <label>
            模型服务
            <select
              aria-label="模型服务"
              value={provider}
              disabled={disabled}
              onChange={(e) => {
                if (backend === "local")
                  setLocalProvider(e.target.value as Provider);
                else setApiProvider(e.target.value as Provider);
                changed();
              }}
            >
              {Object.entries(settings.provider_presets)
                .filter(([, p]) => p.local === (backend === "local"))
                .map(([id, p]) => (
                  <option key={id} value={id}>
                    {p.label}
                  </option>
                ))}
            </select>
          </label>
          <p className="model-privacy">
            {backend === "local"
              ? "材料只发送给这里配置的本机模型服务。请先在 Ollama 或 LM Studio 中下载模型、启动服务，再读取模型列表。"
              : "生成时，提取后的文字及按需分析的图片会发送给所选API服务，费用使用该服务的账户额度。"}
          </p>
          {provider === "kimi_code" && (
            <p className="model-help">
              Kimi Code
              使用独立密钥，服务适用范围与模型权限以账号授权为准；普通材料处理也可以选择“Kimi
              开放平台”。
            </p>
          )}
          <label>
            服务地址 · Base URL
            <input
              aria-label="模型服务地址"
              value={profile.base_url}
              disabled={disabled}
              placeholder={preset.base_url || "https://example.com/v1"}
              onChange={(e) => update({ base_url: e.target.value })}
            />
          </label>
          <label>
            {backend === "local" ? "访问密钥 · 可选" : "API Key"}
            <input
              aria-label="模型API Key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              maxLength={4096}
              disabled={disabled}
              value={profile.api_key || ""}
              placeholder={
                profile.api_key_configured
                  ? "已保存在本机，留空保留；填写可替换"
                  : backend === "local"
                    ? "服务未开启鉴权时可留空"
                    : "粘贴这个服务的API Key"
              }
              onChange={(e) =>
                update({ api_key: e.target.value, clear_api_key: false })
              }
            />
          </label>
          {profile.api_key_configured && (
            <label className="inline-check">
              <input
                type="checkbox"
                checked={profile.clear_api_key || false}
                disabled={disabled}
                onChange={(e) =>
                  update({ clear_api_key: e.target.checked, api_key: "" })
                }
              />
              保存时移除这个服务的密钥
            </label>
          )}
          <small>
            密钥仅保存在这台Mac，不会回显；各服务独立保存。更换服务地址后请重新填写密钥。
          </small>
          <div className="model-id-row">
            <label>
              模型列表
              <select
                aria-label="模型列表"
                value={
                  availableModels.includes(profile.model) ? profile.model : ""
                }
                disabled={disabled || !availableModels.length}
                onChange={(e) => update({ model: e.target.value })}
              >
                <option value="" disabled>
                  {availableModels.length
                    ? "选择模型，或在下方手动填写"
                    : "暂无模型，请读取列表或手动填写"}
                </option>
                {availableModels.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button secondary"
              disabled={disabled}
              onClick={() => void connect("models")}
            >
              {busy === "models" ? (
                <Loader2 size={15} className="spin" />
              ) : (
                <Download size={15} />
              )}
              读取模型列表
            </button>
          </div>
          <label>
            模型ID · 可手动填写
            <input
              aria-label="模型ID"
              value={profile.model}
              disabled={disabled}
              placeholder="填写服务提供的模型ID"
              onChange={(e) => update({ model: e.target.value })}
            />
          </label>
          <details className="model-advanced">
            <summary>更多模型选项</summary>
            <label>
              思考程度
              <select
                aria-label="API思考程度"
                disabled={disabled}
                value={profile.reasoning_effort}
                onChange={(e) => update({ reasoning_effort: e.target.value })}
              >
                <option value="default">沿用服务默认</option>
                <option value="low">低 · low</option>
                <option value="medium">中 · medium</option>
                <option value="high">高 · high</option>
                <option value="xhigh">更高 · xhigh</option>
                <option value="max">最高 · max</option>
              </select>
            </label>
            <small>不同模型支持的档位不同，不确定时沿用默认。</small>
            <label>
              结构化输出
              <select
                disabled={disabled}
                value={profile.output_format}
                onChange={(e) =>
                  update({
                    output_format: e.target
                      .value as ModelProfile["output_format"],
                  })
                }
              >
                <option value="json_object">JSON模式 · 通用</option>
                <option value="json_schema">
                  JSON Schema · 服务支持时使用
                </option>
                <option value="prompt">仅提示词约束 · 兼容模式</option>
              </select>
            </label>
            <div className="model-number-grid">
              <label>
                最大输出Token
                <input
                  type="number"
                  min={256}
                  max={65536}
                  value={profile.max_tokens}
                  disabled={disabled}
                  onChange={(e) =>
                    update({ max_tokens: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                单次材料字数
                <input
                  type="number"
                  min={4000}
                  max={120000}
                  value={profile.context_chars}
                  disabled={disabled}
                  onChange={(e) =>
                    update({ context_chars: Number(e.target.value) })
                  }
                />
              </label>
            </div>
            <small>
              长材料会自动分段。小模型可减少单次材料字数；完整学习笔记适合使用较大上下文的模型。
            </small>
            <label className="inline-check">
              <input
                type="checkbox"
                disabled={disabled}
                checked={profile.supports_images}
                onChange={(e) => update({ supports_images: e.target.checked })}
              />
              这个模型支持图片输入，可用于视频画面分析
            </label>
          </details>
          <div className="model-test-row">
            <button
              className="button secondary"
              disabled={disabled || !profile.model.trim()}
              onClick={() => void connect("test-model")}
            >
              {busy === "test-model" ? (
                <Loader2 size={15} className="spin" />
              ) : (
                <Check size={15} />
              )}
              测试生成
            </button>
            <small>
              发送一条简短测试，不含你的材料；API服务可能计入少量用量。
            </small>
          </div>
          {result && (
            <p
              className={
                "model-test-result " + (result.ok ? "success" : "failed")
              }
              role="status"
            >
              {result.message}
            </p>
          )}
          {preset.docs && (
            <a
              className="text-button"
              href={preset.docs}
              target="_blank"
              rel="noreferrer"
            >
              {preset.label}官方接入说明
            </a>
          )}
        </>
      ) : null}
      <button
        className="button primary model-save"
        disabled={disabled}
        onClick={() => void save()}
      >
        {busy === "save" ? (
          <Loader2 size={16} className="spin" />
        ) : saved ? (
          <Check size={16} />
        ) : (
          <Settings2 size={16} />
        )}{" "}
        {saved ? "模型设置已保存" : "保存模型设置"}
      </button>
    </section>
  );
}
