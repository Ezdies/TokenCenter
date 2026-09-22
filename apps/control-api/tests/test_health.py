import asyncio

import pytest
from fastapi import HTTPException

from control_api import main


def test_liveness() -> None:
    response = asyncio.run(main.live())

    assert response == {"status": "ok"}


def test_readiness_when_dependencies_are_available(monkeypatch: pytest.MonkeyPatch) -> None:
    async def dependency_is_ready(_url: str) -> None:
        return None

    monkeypatch.setattr(main, "_check_postgres", dependency_is_ready)
    monkeypatch.setattr(main, "_check_redis", dependency_is_ready)

    assert asyncio.run(main.ready()) == {"status": "ready"}


def test_readiness_hides_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def dependency_is_down(_url: str) -> None:
        raise ConnectionError("sensitive connection details")

    monkeypatch.setattr(main, "_check_postgres", dependency_is_down)
    monkeypatch.setattr(main, "_check_redis", dependency_is_down)

    with pytest.raises(HTTPException) as captured:
        asyncio.run(main.ready())

    assert captured.value.status_code == 503
    assert captured.value.detail == "A required dependency is unavailable"
