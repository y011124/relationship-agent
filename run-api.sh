#!/usr/bin/env zsh
set -euo pipefail
cd "$(dirname "$0")"
export PERSONA_MODE=api
export RELATIONSHIP_MODEL="${RELATIONSHIP_MODEL:-glm-5.3}"
export RELATIONSHIP_PROTOCOL="${RELATIONSHIP_PROTOCOL:-chat-completions}"
export RELATIONSHIP_BASE_URL="${RELATIONSHIP_BASE_URL:-https://open.bigmodel.cn/api/paas/v4}"
export PERSONA_PROVIDER_LABEL="${PERSONA_PROVIDER_LABEL:-GLM · 智谱}"
api_port="${PERSONA_PORT:-8770}"
export PERSONA_ORIGIN="http://127.0.0.1:$api_port"
if [[ -z "${PERSONA_API_KEY:-}${GLM_API_KEY:-}" ]]; then
  read -rs "PERSONA_API_KEY?粘贴你有权用于此项目的模型 Key（隐藏输入），然后回车："
  export PERSONA_API_KEY
  echo
fi
exec .venv/bin/python persona_app.py --port "$api_port"
