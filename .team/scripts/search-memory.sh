#!/usr/bin/env bash
# Agent Memory & Knowledge Search Wrapper
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="${SCRIPT_DIR}/../memory"

uv run "${MEMORY_DIR}/search.py" "$@"
