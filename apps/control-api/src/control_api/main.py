import asyncio

import asyncpg
from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis

from control_api.settings import Settings

app = FastAPI(title="TokenCenter Control API", version="0.1.0")


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
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="A required dependency is unavailable") from error
    return {"status": "ready"}


async def _check_postgres(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, timeout=2)
    try:
        await connection.fetchval("SELECT 1")
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
