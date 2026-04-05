FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ARG APP_HOME=/app

WORKDIR ${APP_HOME}

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
ENV PYTHONPATH=""

RUN apt-get update && apt-get install --no-install-recommends -y \
  build-essential \
  libpq-dev \
  gettext \
  wait-for-it \
  && rm -rf /var/lib/apt/lists/*

# signer 开发镜像只安装 signer 自己的依赖，避免继续复用主应用的大体积依赖集。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=signer/pyproject.toml,target=signer/pyproject.toml \
    --mount=type=bind,source=signer/uv.lock,target=signer/uv.lock \
    uv sync --project signer --locked --group dev --no-group production

# 开发镜像只复制 signer 自己的项目目录，避免把整仓源码打进 signer 镜像。
COPY signer ${APP_HOME}/signer

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=signer/pyproject.toml,target=signer/pyproject.toml \
    --mount=type=bind,source=signer/uv.lock,target=signer/uv.lock \
    uv sync --project signer --locked --group dev --no-group production

RUN chmod +x ${APP_HOME}/signer/compose/dev/start

ENV PATH="/app/signer/.venv/bin:$PATH"

ENTRYPOINT []
