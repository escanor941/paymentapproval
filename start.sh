#!/usr/bin/env bash
set -e

PORT_TO_USE="${PORT:-8000}"

python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT_TO_USE"
