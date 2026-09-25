import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import HTTPException

from control_api import main


class MockResponseStream(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def test_liveness() -> None:
    response = asyncio.run(main.live())

    assert response == {"status": "ok"}


def test_readiness_when_dependencies_are_available(monkeypatch: pytest.MonkeyPatch) -> None:
    async def dependency_is_ready(_url: str) -> None:
        return None

    monkeypatch.setattr(main, "_check_postgres", dependency_is_ready)
    monkeypatch.setattr(main, "_check_redis", dependency_is_ready)
    monkeypatch.setattr(main, "_check_litellm", dependency_is_ready)

    assert asyncio.run(main.ready()) == {"status": "ready"}


def test_readiness_hides_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def dependency_is_down(_url: str) -> None:
        raise ConnectionError("sensitive connection details")

    monkeypatch.setattr(main, "_check_postgres", dependency_is_down)
    monkeypatch.setattr(main, "_check_redis", dependency_is_down)
    monkeypatch.setattr(main, "_check_litellm", dependency_is_down)

    with pytest.raises(HTTPException) as captured:
        asyncio.run(main.ready())

    assert captured.value.status_code == 503
    assert captured.value.detail == "A required dependency is unavailable"


def test_chat_completions_are_forwarded_to_litellm() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["authorization"] = request.headers.get("authorization")
        observed["body"] = request.content
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=MockResponseStream(b'{"choices":[{"message":{"content":"mock:gateway"}}]}'),
        )

    async def exercise_gateway() -> httpx.Response:
        litellm_client = httpx.AsyncClient(
            base_url="http://litellm:4000",
            transport=httpx.MockTransport(handler),
        )
        main.app.state.litellm_client = litellm_client
        try:
            async with httpx.AsyncClient(
                base_url="http://gateway",
                transport=httpx.ASGITransport(app=main.app),
            ) as gateway_client:
                return await gateway_client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer public-key"},
                    json={"model": "auto", "messages": []},
                )
        finally:
            await litellm_client.aclose()

    response = asyncio.run(exercise_gateway())

    assert response.status_code == 200
    assert response.headers["x-token-center-gateway"] == "agent-gateway"
    assert response.json()["choices"][0]["message"]["content"] == "mock:gateway"
    assert observed == {
        "method": "POST",
        "path": "/v1/chat/completions",
        "authorization": "Bearer public-key",
        "body": b'{"model":"auto","messages":[]}',
    }


def test_litellm_connection_error_is_hidden() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("internal address")

    async def exercise_gateway() -> httpx.Response:
        litellm_client = httpx.AsyncClient(
            base_url="http://litellm:4000",
            transport=httpx.MockTransport(handler),
        )
        main.app.state.litellm_client = litellm_client
        try:
            async with httpx.AsyncClient(
                base_url="http://gateway",
                transport=httpx.ASGITransport(app=main.app),
            ) as gateway_client:
                return await gateway_client.get("/v1/models")
        finally:
            await litellm_client.aclose()

    response = asyncio.run(exercise_gateway())

    assert response.status_code == 502
    assert response.json() == {"detail": "LiteLLM is unavailable"}


def test_streaming_response_is_forwarded_without_changing_sse_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'"stream":true' in request.content
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockResponseStream(b'data: {"chunk":1}\n\n', b"data: [DONE]\n\n"),
        )

    async def exercise_gateway() -> httpx.Response:
        litellm_client = httpx.AsyncClient(
            base_url="http://litellm:4000",
            transport=httpx.MockTransport(handler),
        )
        main.app.state.litellm_client = litellm_client
        try:
            async with httpx.AsyncClient(
                base_url="http://gateway",
                transport=httpx.ASGITransport(app=main.app),
            ) as gateway_client:
                return await gateway_client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer public-key"},
                    json={"model": "auto", "messages": [], "stream": True},
                )
        finally:
            await litellm_client.aclose()

    response = asyncio.run(exercise_gateway())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == b'data: {"chunk":1}\n\ndata: [DONE]\n\n'
