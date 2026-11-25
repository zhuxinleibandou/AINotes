# AINotes · 拾页

在 Mac 浏览器中，把一份材料整理为速览、详细笔记、长图、脑图、课程和测试。生成可选择本机 Codex、模型 API 或本地模型；文件和学习记录保存在本机。

源码仓库：[zhuxinleibandou/AINotes](https://github.com/zhuxinleibandou/AINotes)。当前版本为面向 Apple Silicon Mac 的个人本地 Beta，默认只监听本机，不提供多用户或公网托管。

## 从源码运行

准备 Apple Silicon Mac、Python 3.12（uv 可安装）、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 22 或更新版本、FFmpeg 和 Apple 命令行工具。使用 Codex 生成时还需安装并登录支持本应用参数的 Codex CLI；API 和本地模型方式不要求 Codex 登录。

```sh
git clone https://github.com/zhuxinleibandou/AINotes.git
cd AINotes
brew install uv ffmpeg
xcode-select --install
uv sync --python 3.12 --locked
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python start.py
```

已安装 Apple 命令行工具可跳过 `xcode-select --install`。没有 Homebrew 时，按各工具官网安装。浏览器打开 `http://127.0.0.1:8317/`，在设置页选择生成方式并测试。下载或克隆后也可以双击 `启动拾页.command`；源码首次启动需要 npm 构建页面，预构建 Beta 安装包则不需要 Node.js。

项目运行时会在根目录创建 `data/`，不会自动读取其他目录的笔记。请勿同时启动不同目录的副本占用8317端口。停止服务可在启动窗口按 Control+C；已有材料和学习进度保留。

## 打开本地 Beta

打开 DMG，把拾页文件夹拖到「应用程序」。在复制后的文件夹内双击 **启动拾页.command**，浏览器会打开 <http://127.0.0.1:8317/>。终端窗口需要保持打开。再次双击会复用已启动的网站。

版本：**0.1.0-beta.2**。适用 Apple Silicon Mac。需要 uv、FFmpeg 和 Apple 命令行工具；使用 Codex 生成时另需已登录且支持本应用参数的 Codex CLI，也可在设置中配置模型 API 或本地模型服务。发布包已包含构建页面，正常使用不需要 Node.js；启动脚本按锁文件准备和更新 Python 环境。安装、升级、备份与已知限制见 [BETA.md](BETA.md)。

在 macOS 上打包可运行 `npm --prefix frontend ci`、`npm --prefix frontend run build`，再执行 `python3 scripts/package_dmg.py`。DMG、ZIP 和各自的 SHA-256 校验文件生成在 `release/`。

## 使用

1. 选择粘贴链接、上传文件、粘贴正文或现场录音。
2. 可填写学习要求，例如“保留关键数字，重点解释步骤”。选择总结格式，按需勾选课程。
3. 点击“开始整理”。读取和生成在后台进行，可以离开页面，在笔记库回来查看。
4. 用“一页速览”看全貌，用“详细笔记”深入阅读；需要时在“原文”页核对材料，结果与导出不显示原文依据编号。
5. 长图可导出 1080px PNG；过长时按卡片边界分图打包 ZIP。脑图可缩放、展开收起、查看要点，导出 SVG、PNG 或 Markdown 大纲。
6. 课程先生成目录，再准备单节讲解与练习；每三节设阶段测验，结束可做最终测试。测试支持单选、多选和判断，答题与完成进度自动保存，全部作答后可重做错题。
7. 修改笔记会保存新版本。已有课程与测验保留，过期内容会提示更新；重新生成的旧课程和答题记录可在“历史课程与答题记录”中查看。
8. 首页最近笔记和笔记库卡片右上角均有删除按钮。确认后清理该笔记全部版本、课程与答题历史、任务记录及资料库内的原材料副本、缓存和导出文件；删除不可撤销。正在处理的笔记先点击停止任务，待处理完全退出后再确认。电脑其他位置的原始文件、已下载文件和手动备份由你管理，不随笔记删除。

发布包以空笔记库启动。开发目录保留的功能验收笔记与平台失败记录不会随包分发。

## 输入与边界

| 输入 | 处理方式 |
|---|---|
| 正文、TXT、MD | 无预设字符上限，完整保留原文；按长度分段并分层归纳，支持UTF-8/UTF-16/GB18030文本 |
| DOCX | MarkItDown 提取正文与表格，Apple Vision 识别内嵌图片文字 |
| PPTX | 按幻灯片保留定位、文字、表格与插图文字 |
| PDF | 按页提取文字；文字极少的页面启用本地 OCR |
| PNG/JPG/WEBP/BMP/TIFF/HEIC | Mac Apple Vision 本地 OCR |
| 音视频文件 | 每20分钟一段本地转写，保留连续时间戳与已完成分段；FFmpeg解码 |
| YouTube/B站/抖音 | YouTube/B站优先字幕或音轨；抖音优先公开分享页自动游客会话，个人页 modal_id 自动规范化，失败再尝试yt-dlp |
| 小宇宙 | 从单集页面获取公开音频，再转写 |
| 公众号/普通网页 | 提取正文与表格，公众号要求具体文章正文而非平台登录首页 |
| 现场录音 | 开始、暂停、继续、结束、试听、下载和提交 |

旧版 `.doc/.ppt` 请先另存为 `.docx/.pptx`。文件支持多选、拖入、继续添加，不设文件数量或累计导入配额；每份单独创建笔记并串行整理，单个文件上限500MB。图片 OCR 侧重文字，复杂图表与数字仍需人工核对。转写可能出现同音词和术语错误。

单条音视频链接最长600分钟（含600分钟），平台信息可确定时提前检查，下载后再次核实时长；无法确认时长时不继续转写，不以截取前600分钟代替完整处理。此时长限制不用于本地文件。

长图默认展示知识要点，支持切换完整内容；两种视图均采用1080px导出，超长内容按完整卡片、段落或表格行分图。切换视图不重新调用AI。

视频默认分析字幕/语音，页面明确注明处理范围。“补充视频画面分析”使用均匀抽样与场景切换抽帧，最多20帧，合并语音与画面来源后重新整理笔记。没有语音的视频也可在失败页单独尝试画面分析。抽样可能遗漏短暂画面，不承诺逐帧完整理解。

平台的访问授权、Cookie、地区及反爬限制会影响成功率。识别链接不等于取得内容。失败时保留原因，支持配置平台授权后重试、上传本地文件或粘贴文稿。抖音默认先尝试公开分享页的自动游客会话，不需要用户导出账号Cookie，游客标识仅保存在单次请求内存中。设置中仍可选导入 Netscape 格式 `cookies.txt`，只保留所选平台域名的 Cookie，不自动读取浏览器账号，不将 Cookie 发送给生成模型。

## 模型设置与切换

设置页提供三种生成方式：

- **本机 Codex**：沿用已有登录，可指定模型ID；留空沿用本机默认模型与思考程度。
- **模型 API**：预置 DeepSeek、Kimi 开放平台、Kimi Code、GLM，支持其他 OpenAI 兼容接口。填写服务自己的 API Key 和模型ID，可读取模型列表、执行一次简短测试生成。Kimi Code 使用独立密钥，适用范围与模型权限以服务授权为准；GLM 预置普通 API 接口。
- **本地模型**：支持 Ollama、LM Studio 和其他本机 OpenAI 兼容服务。先在对应软件中下载模型并启动服务，再读取列表；本应用不会自动安装大模型。地址限本机 localhost、127.0.0.1 或 ::1，访问密钥可选。

各服务分别保存地址、模型与密钥，可配置思考程度、输出格式、输出Token、单次材料字数和图片支持；不同模型支持的选项不同，默认沿用服务思考配置。仅支持对话补全兼容接口，返回内容必须通过完整结构检查才保存为成功。

**有排队、运行、正在暂停或正在取消的任务时，不能切换或保存模型设置。** 设置页先点击“暂停任务后切换”，等待显示“任务已暂停，可以切换模型”，再选择并保存。暂停请求不会立即解锁，后台确认当前请求与处理停止后才开放。后台接口同样检查，避免其他页面绕过限制。已解析材料和已完成内容保留，未完成的一次生成需重做；保存后可手动“继续已暂停的任务”，使用已保存的模型处理。不会自动暂停或自动恢复你的任务。

最大输出Token与单次材料字数均提供8K、64K、384K和自定义选项（1K=1024）。自定义不设应用最大值，保留已有设置；实际可用范围取决于所选模型与服务。材料字数是文字数量，不等于Token数。有效下限仍为输出256 Token、材料4000字。

测试生成只发送一条无材料的简短请求，API 服务可能计入少量用量。真实模型可用性以你提供密钥后或启动本地服务后的测试结果为准。

## 数据与隐私

- 服务只监听 `127.0.0.1:8317`，阻止非本机 Host 及外站写入来源；不对局域网开放。
- `data/library.sqlite3`：笔记、任务、版本、课程、答题记录。
- `data/materials/`：原始材料、提取文本及处理检查点。
- `data/exports/`：按笔记及版本保留导出文件。
- `data/secrets/`：各模型服务的 API Key 与可选平台 Cookie，目录权限700、文件权限600。模型密钥与服务地址绑定，不写入笔记数据库、不返回浏览器或记录在浏览器本地存储。
- 模型默认下载到 Hugging Face 本机缓存，large-v3-turbo 权重约1.6GB；首次转写需要下载，后续在本地识别。
- 本地保存不代表全程离线：网页需联网获取；选择 Codex 或模型 API 时，材料文字和按需抽取的图片会发送给所选服务；选择本地模型时，只发送给配置的本机模型地址，不自动回退到云端。
- Codex 运行在专用临时目录，沿用本机模型及连接配置、认证状态；不继承用户 MCP、插件、Hook，关闭 Shell、浏览器及多代理功能，使用只读沙箱和结构化输出校验。材料通过标准输入提交，不作为命令执行。
- 队列串行执行；服务关闭后运行中的任务变为“可继续”，重新处理复用已保存的正文与长材料分段结果。
- 清理缓存仅删除可重新生成的编译/分段缓存，保留资料、版本和导出。对平台会话的撤销需要在平台自身完成；本地“移除”只移除这份 Cookie 文件。

## 开发与验证

```sh
uv sync --python 3.12 --locked
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8317
```

前端开发：

```sh
cd frontend
npm ci
npm run dev
```

前端开发地址是 `http://127.0.0.1:5173`，通过代理访问后端。正式启动前运行 `npm run build`。

核心验证：

```sh
.venv/bin/python -m pytest -q
npm --prefix frontend run build
```

真实集成验收脚本保存在 `tests/`：

- `smoke_codex.py`：真实 Codex 连接与结构化输出，消耗账号额度。
- `platform_probe.py`：各视频平台真实信息获取，不生成笔记；抖音样例由 `AINOTES_DOUYIN_TEST_URL` 环境变量提供，不内置个人链接。
- `web_probe.py`：网页解析与错误提示检查。
- `media_probe.py`：中文 OCR、本地音频转写；使用 `output/audio/verification-speech.wav` 的本地 OmniVoice 验收音频。
- `vision_probe.py`：用语音未提到的屏幕编号与数字检验画面补充，调用真实 Codex，消耗额度，使用独立验收数据库。

本机验收时生成的结果、截图及媒体放在 `output/verification/` 和 `output/playwright/`，不纳入源码仓库或发布包；可复现检查及历史覆盖范围见 `VERIFICATION.md`。普通单元测试不调用 Codex或下载模型。

## 主要接口

- `POST /api/import`、`POST /api/import/file`：导入并创建后台任务。
- `GET /api/notes?q=`、`GET/PUT /api/notes/{id}`：搜索、阅读及带版本检查的保存。
- `GET /api/notes/{id}/delete-info`、`DELETE /api/notes/{id}`：删除前任务检查，清理该笔记与全部历史和资料库内文件；在途任务返回409。
- `POST /api/notes/{id}/generate`：summary/course/lesson/quiz/stage/vision。
- `GET /api/jobs/{id}`、`POST /api/jobs/{id}/cancel|retry`：任务查询、取消与重试。
- `PUT /api/notes/{id}/progress`：以epoch校验题目版本，原子合并本次变更的答案、新完成章节与阅读位置；答案null用于重做。
- `GET /api/notes/{id}/versions|learning-history`：笔记与学习历史。
- `GET /api/notes/{id}/export/markdown|overview|outline`：Markdown 导出。
- `POST /api/notes/{id}/exports`：保留已导出的图片或ZIP。
- `GET/PUT /api/settings`：运行状态与生成模型设置。
- `GET /api/settings/tasks`、`POST /api/settings/pause-tasks|resume-tasks`：模型切换前暂停及手动继续任务。
- `POST /api/settings/models|test-model`：读取模型列表、检查一次结构化返回，支持尚未保存的配置。

不包含多人账号、收费、公开分享、多资料合并、播客和记忆卡。

## 贡献与反馈

开发和提交约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。反馈请说明系统、版本、材料类型、处理阶段与最小复现步骤。不要提交 API Key、Cookie、个人材料或整个资料库。

源码仓库不包含 `data/`、`output/`、`release/`、本机模型、虚拟环境、node_modules、账号信息或个人声音。预构建发布包由 `scripts/package_beta.py` 生成；它使用明确文件清单，打包前先完成前端构建，包内不含已有笔记或密钥。

## 许可证

Copyright © 2026 zhuxinleibandou。AINotes 自有源码采用 [GNU AGPL v3](LICENSE)（`AGPL-3.0-only`），第三方依赖保留各自许可证。

使用、修改和分发时请阅读完整许可证；部署修改版本并通过网络向用户提供服务时，应按AGPL条款向这些用户提供对应源码。第三方模型API、账号服务、模型权重及平台内容不因本仓库开源而改变原有许可或服务条款。依赖说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
