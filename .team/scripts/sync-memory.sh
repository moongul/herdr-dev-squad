#!/usr/bin/env bash
# Agent Memory & Knowledge Indexer Wrapper
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="${SCRIPT_DIR}/../memory"
ACTIVE_FILE="${SCRIPT_DIR}/../active_project"

# 인자가 지정되지 않은 경우 현재 활성 프로젝트를 기본 타깃으로 동기화
if [ $# -eq 0 ] && [ -f "$ACTIVE_FILE" ]; then
    ACTIVE_PROJ="$(cat "$ACTIVE_FILE" | tr -d '[:space:]')"
    if [ -n "$ACTIVE_PROJ" ]; then
        exec uv run "${MEMORY_DIR}/indexer.py" --project "$ACTIVE_PROJ"
    fi
fi

exec uv run "${MEMORY_DIR}/indexer.py" "$@"
