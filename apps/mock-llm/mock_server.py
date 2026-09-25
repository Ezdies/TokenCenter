"""Tiny OpenAI-compatible server used only by the LiteLLM integration spike."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "not found"})
            return

        size = int(self.headers.get("Content-Length", "0"))
        request: dict[str, Any] = json.loads(self.rfile.read(size) or b"{}")
        model = str(request.get("model", "unknown"))
        if request.get("stream") is True:
            self._stream_chat_completion(model)
            return

        self._json(
            200,
            {
                "id": "chatcmpl-token-center-spike",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"mock:{model}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def log_message(self, message: str, *args: object) -> None:
        print(f"mock-llm: {message % args}", flush=True)

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_chat_completion(self, model: str) -> None:
        created = int(time.time())
        chunks: list[dict[str, object]] = [
            {
                "id": "chatcmpl-token-center-spike",
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": f"mock:{model}"},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-token-center-spike",
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
