#!/usr/bin/env zsh
set -euo pipefail

cd "$(dirname "$0")"

api_port="${RELATIONSHIP_PORT:-8767}"
api_model="${RELATIONSHIP_MODEL:-glm-5.3}"
api_base_url="${RELATIONSHIP_BASE_URL:-https://open.bigmodel.cn/api/paas/v4}"
api_protocol="${RELATIONSHIP_PROTOCOL:-chat-completions}"
api_memory_dir="${RELATIONSHIP_MEMORY_DIR:-$PWD/memory/v2}"

if [[ -z "${GLM_API_KEY:-}" ]]; then
  read -rs "GLM_API_KEY?粘贴 GLM API Key，然后按回车："
  export GLM_API_KEY
  echo
fi

exec .venv/bin/python web_app.py \
  --mode api \
  --port "$api_port" \
  --model "$api_model" \
  --protocol "$api_protocol" \
  --base-url "$api_base_url" \
  --memory-dir "$api_memory_dir" \
  --api-key-env GLM_API_KEY
