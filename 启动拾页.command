#!/bin/zsh
set -e
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
trap 'echo "启动未完成，请查看上方提示。"; read "?按回车退出"' ZERR
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo '此 Beta 需要 Apple Silicon Mac。'
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/'
  read '?按回车退出'
  exit 1
fi
echo '正在检查并按锁文件更新本地运行环境…'
uv sync --python 3.12 --locked
if [[ ! -f frontend/dist/index.html ]]; then
  if ! command -v npm >/dev/null 2>&1 && [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    source "$HOME/.nvm/nvm.sh"
  fi
  echo '正在准备页面…'
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi
exec .venv/bin/python start.py
