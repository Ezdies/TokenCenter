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
  echo "Stack failed: Agent Gateway is not ready: $readiness" >&2
  exit 1
fi

headers_file="$(mktemp)"
trap 'rm -f "$headers_file"' EXIT

response="$(curl --fail --silent --show-error \
  "$base_url/v1/chat/completions" \
  --dump-header "$headers_file" \
  --header "Authorization: Bearer $master_key" \
  --header 'Content-Type: application/json' \
  --data '{"model":"auto","messages":[{"role":"user","content":"route this request"}]}'
)"

if [[ "$response" != *'mock:spike-free'* ]]; then
  echo "Stack failed: expected the free deployment, received: $response" >&2
  exit 1
fi

gateway_header_found=false
while IFS= read -r header; do
  if [[ "${header,,}" == x-token-center-gateway:* ]]; then
    gateway_header_found=true
    break
  fi
done < "$headers_file"

if [[ "$gateway_header_found" != true ]]; then
  echo "Stack failed: inference response did not pass through Agent Gateway." >&2
  exit 1
fi

stream_response="$(curl --fail --silent --show-error --no-buffer \
  "$base_url/v1/chat/completions" \
  --header "Authorization: Bearer $master_key" \
  --header 'Content-Type: application/json' \
  --data '{"model":"auto","stream":true,"messages":[{"role":"user","content":"stream this request"}]}'
)"

if [[ "$stream_response" != *'mock:spike-free'* || "$stream_response" != *'data: [DONE]'* ]]; then
  echo "Stack failed: streaming response was not forwarded correctly: $stream_response" >&2
  exit 1
fi

published_litellm_port="$(docker compose port litellm 4000 2>/dev/null || true)"
if [[ "$published_litellm_port" =~ :[1-9][0-9]*$ ]]; then
  echo "Stack failed: LiteLLM must not publish port 4000 on the host." >&2
  exit 1
fi

echo "Stack passed: dashboard, Agent Gateway, PostgreSQL with pgvector, Redis, internal LiteLLM and mock provider are ready."
