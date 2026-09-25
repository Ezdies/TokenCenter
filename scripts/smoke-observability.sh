#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${LANGFUSE_URL:-}" ]]; then
  langfuse_url="$LANGFUSE_URL"
else
  published_address="$(docker compose --profile observability port langfuse-web 3000)"
  langfuse_url="http://${published_address/0.0.0.0/127.0.0.1}"
fi

web_health="$(curl --fail --silent --show-error "$langfuse_url/api/public/health")"
if [[ "$web_health" != *'"status":"OK"'* && "$web_health" != *'"status":"ok"'* ]]; then
  echo "Observability failed: unexpected Langfuse web health response: $web_health" >&2
  exit 1
fi

docker compose --profile observability exec -T langfuse-worker \
  node -e "fetch('http://langfuse-worker:3030/api/ready').then(async r => { if (!r.ok) { console.error(await r.text()); process.exit(1) } }).catch(error => { console.error(error); process.exit(1) })"

./scripts/smoke-stack.sh

echo "Observability passed: Langfuse web and worker are ready, and the inference path remains healthy."
