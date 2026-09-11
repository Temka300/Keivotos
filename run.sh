#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "[ERROR] uv is required to run Keivotos from source." >&2
    echo "[ERROR] Install it from https://docs.astral.sh/uv/" >&2
    exit 1
fi

exec uv run --locked --python 3.11 run.py "$@"
