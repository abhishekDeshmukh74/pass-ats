#!/usr/bin/env bash
set -e

# Log LaTeX compiler availability so Render boot logs are easy to diagnose
if command -v xelatex >/dev/null 2>&1; then
  echo "[start.sh] xelatex found at: $(command -v xelatex)"
elif command -v pdflatex >/dev/null 2>&1; then
  echo "[start.sh] pdflatex found at: $(command -v pdflatex) (xelatex not found)"
else
  echo "[start.sh] WARNING: no LaTeX compiler found — .tex resume uploads will fail."
fi

uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
