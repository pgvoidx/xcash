#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

ENV_FILE="${ENV_FILE:-.env.dev}"

if [[ -f "${ENV_FILE}" ]]; then
  # 本地开发统一加载 .env.dev，保证 Django 与 Celery 使用相同依赖配置。
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

# 开发脚本统一默认指向 dev settings，避免继续散落历史 local 命名。
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.dev}"
export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"

# 开发环境仅对 worker 开启热重载；beat 单独运行，避免 watchfiles 重启后遗留重复调度器。
exec uv run watchfiles --filter python celery.__main__.main --args "-A config.celery worker -l INFO --pool=threads --concurrency=8"
