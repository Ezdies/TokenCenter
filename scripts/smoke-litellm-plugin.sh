#!/usr/bin/env bash
set -euo pipefail

response="$({ curl --fail --silent --show-error \
  http://127.0.0.1:4000/v1/chat/completions \
  --header 'Authorization: Bearer sk-local-development-only' \
  --header 'Content-Type: application/json' \
  --data '{"model":"auto","messages":[{"role":"user","content":"route this request"}]}' ; } 2>&1)"

if [[ "$response" != *'mock:spike-free'* ]]; then
  echo "Spike failed: expected the free deployment, received: $response" >&2
  exit 1
fi

echo "Spike passed: model=auto was narrowed to openai/spike-free."

