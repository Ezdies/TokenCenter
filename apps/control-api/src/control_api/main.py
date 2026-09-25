import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis
from starlette.responses import StreamingResponse

from control_api.inference_proxy import forward_to_litellm
from control_api.settings import Settings


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_environment()
    timeout = httpx.Timeout(settings.litellm_timeout_seconds, connect=5)
    async with httpx.AsyncClient(base_url=settings.litellm_base_url, timeout=timeout) as client:
        application.state.litellm_client = client
        yield


app = FastAPI(title="TokenCenter Agent Gateway", version="0.1.0", lifespan=lifespan)


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    settings = Settings.from_environment()
    try:
        await asyncio.gather(
            _check_postgres(settings.database_url),
            _check_redis(settings.redis_url),
            _check_litellm(settings.litellm_base_url),
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="A required dependency is unavailable") from error
    return {"status": "ready"}


@app.post("/v1/chat/completions", tags=["inference"])
async def chat_completions(request: Request) -> StreamingResponse:
    return await forward_to_litellm(request, "/v1/chat/completions")


@app.get("/v1/models", tags=["inference"])
async def models(request: Request) -> StreamingResponse:
    return await forward_to_litellm(request, "/v1/models")


async def _check_postgres(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, timeout=2)
    try:
        vector_version = await connection.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        if vector_version is None:
            raise RuntimeError("The vector extension is unavailable")
    finally:
        await connection.close(timeout=2)


async def _check_redis(redis_url: str) -> None:
    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_litellm(litellm_base_url: str) -> None:
    async with httpx.AsyncClient(base_url=litellm_base_url, timeout=2) as client:
        response = await client.get("/health/liveliness")
        response.raise_for_status()
