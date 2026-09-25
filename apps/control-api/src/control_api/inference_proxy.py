from collections.abc import AsyncIterator, Mapping

import httpx
from fastapi import HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


async def forward_to_litellm(request: Request, path: str) -> StreamingResponse:
    client = _litellm_client(request)
    headers = _forward_headers(request.headers)
    body = await request.body()

    upstream_request = client.build_request(
        request.method,
        path,
        params=request.query_params,
        headers=headers,
        content=body,
    )

    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="LiteLLM is unavailable") from error

    response_headers = _response_headers(upstream_response.headers)
    response_headers["x-token-center-gateway"] = "agent-gateway"

    return StreamingResponse(
        _response_body(upstream_response),
        status_code=upstream_response.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream_response.aclose),
    )


def _litellm_client(request: Request) -> httpx.AsyncClient:
    client = getattr(request.app.state, "litellm_client", None)
    if not isinstance(client, httpx.AsyncClient):
        raise RuntimeError("LiteLLM client is not initialized")
    return client


def _forward_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in _HOP_BY_HOP_HEADERS | {"host", "content-length"}
    }


def _response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value for name, value in headers.items() if name.lower() not in _HOP_BY_HOP_HEADERS | {"content-length"}
    }


async def _response_body(response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in response.aiter_raw():
        yield chunk
