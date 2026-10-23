# 参与 AINotes

当前支持 Apple Silicon Mac，本地单人使用。请先阅读 [README.md](README.md) 的运行方式和功能边界。

## 开发

```sh
uv sync --python 3.12 --locked
npm --prefix frontend ci
.venv/bin/python -m pytest -q
npm --prefix frontend run build
```

前端开发服务为 `npm --prefix frontend run dev`，另开后端服务：

```sh
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8317
```

`pytest` 使用临时资料库和受控模型结果，不需要真实API密钥、调用Codex或下载转写模型。`tests/*_probe.py`、`tests/smoke_codex.py` 是手动集成脚本，可能访问平台、下载模型或使用账号额度；仅在理解对应脚本后自行运行。音频/画面验收素材需自行准备，不随仓库提供。

## 修改和提交

- 保持改动聚焦，并描述触发条件、变更后的行为和验证结果。
- 更改依赖时同步锁文件；前端提交源码，构建产物由打包时生成。
- 新增材料解析或平台支持时，区分链接识别、真实获取和成功生成，不把模拟返回当作真实模型或平台验收。
- 模型配置修改不得绕过任务暂停检查；没有在途处理时才可保存或切换。
- 不提交个人材料、数据库、导出文件、密钥、Cookie、本地配置或模型权重。请在提交前检查暂存文件清单和差异。

## 反馈问题

通过仓库 Issues 提供系统版本、应用版本、最小复现步骤和不含敏感信息的错误文本。附件仅使用你有权分享的最小样例；不要上传整个 `data/` 或包含 API Key/Cookie 的日志。
