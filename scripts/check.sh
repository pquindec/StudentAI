#!/usr/bin/env bash
# Ejecuta todas las comprobaciones (lint, tipos, pruebas) de backend, frontend y Rust.
# Uso: scripts/check.sh [backend|frontend|rust]   (sin argumento: todo)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
what="${1:-all}"

if [[ $what == all || $what == backend ]]; then
  echo "── backend"
  cd "$ROOT/backend"
  uv run --frozen ruff check .
  uv run --frozen ruff format --check .
  uv run --frozen mypy
  uv run --frozen pytest -q -W ignore::DeprecationWarning
fi

if [[ $what == all || $what == frontend ]]; then
  echo "── frontend"
  cd "$ROOT/app"
  npm run --silent typecheck
  npm run --silent lint
  npm run --silent format:check
  npm run --silent test
fi

if [[ $what == all || $what == rust ]]; then
  echo "── rust"
  cd "$ROOT/app/src-tauri"
  cargo fmt --check
  cargo clippy --all-targets --quiet -- -D warnings
  cargo test --quiet
fi
echo "✔ Todo correcto"
