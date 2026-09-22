FROM ghcr.io/astral-sh/uv:0.12.17-python3.13-trixie-slim@sha256:5b7499c3e4048c8f9afcca908c2f2c486923cd441b857976fb6a871e6a090737

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/control-api/pyproject.toml apps/control-api/pyproject.toml
COPY packages/policy-engine/pyproject.toml packages/policy-engine/pyproject.toml
COPY apps/control-api/src apps/control-api/src
COPY packages/policy-engine/src packages/policy-engine/src

RUN uv sync --frozen --no-dev --package control-api --no-editable

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "control_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--root-path", "/api"]

