#!/bin/zsh
set -e
support="$HOME/Library/Application Support/AINotes"
export QUICKLEARN_DATA="$support/data"
export UV_PROJECT_ENVIRONMENT="$support/python-@VERSION@"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$support"
exec "${0:A:h}/project/启动拾页.command"
