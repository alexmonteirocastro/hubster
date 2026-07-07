# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder-test

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --group dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --group dev

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /home/app --create-home app

COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    HOME="/home/app"

USER app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim-bookworm AS test

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /home/app --create-home app

COPY --from=builder-test --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    HOME="/home/app"

USER app

CMD ["pytest", "-v"]
