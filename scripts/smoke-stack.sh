#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${TOKEN_CENTER_URL:-}" ]]; then
  base_url="$TOKEN_CENTER_URL"
else
  published_address="$(docker compose port reverse-proxy 80)"
  base_url="http://${published_address/0.0.0.0/127.0.0.1}"
fi

master_key="${LITELLM_MASTER_KEY:-$(docker compose exec -T litellm printenv LITELLM_MASTER_KEY)}"

curl --fail --silent --show-error "$base_url/" >/dev/null

readiness="$(curl --fail --silent --show-error "$base_url/api/health/ready")"
if [[ "$readiness" != *'"status":"ready"'* ]]; then
  echo "Stack failed: Control API is not ready: $readiness" >&2
  exit 1
fi

response="$(curl --fail --silent --show-error \
  "$base_url/v1/chat/completions" \
  --header "Authorization: Bearer $master_key" \
  --header 'Content-Type: application/json' \
  --data '{"model":"auto","messages":[{"role":"user","content":"route this request"}]}'
)"

if [[ "$response" != *'mock:spike-free'* ]]; then
  echo "Stack failed: expected the free deployment, received: $response" >&2
  exit 1
fi

echo "Stack passed: dashboard, Control API, PostgreSQL, Redis, LiteLLM and mock provider are ready."
