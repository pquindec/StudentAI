#!/usr/bin/env bash
# Prepara el backend Python autocontenido que se incluye dentro del .app:
#   app/src-tauri/resources/backend-runtime/
#     python/         CPython standalone (python-build-standalone, gestionado por uv)
#     site-packages/  dependencias de producción (sin las de desarrollo)
#     app/            código del backend
#     launch.py       punto de entrada (se ejecuta con `python -I`)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
OUT="$ROOT/app/src-tauri/resources/backend-runtime"
PY_VERSION="3.13"

echo "→ Limpiando $OUT"
rm -rf "$OUT"
mkdir -p "$OUT"

echo "→ Copiando CPython $PY_VERSION standalone"
# No se instala nada aquí: si falta, `uv sync` en backend/ lo descarga.
PY_BIN="$(uv python find --no-project "$PY_VERSION")"
# uv expone Python a través de enlaces simbólicos: se resuelve la carpeta REAL.
PY_HOME="$(cd -P "$(dirname "$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$PY_BIN")")/.." && pwd)"
case "$PY_HOME" in
  "$HOME/.local/share/uv/python/"*) ;;
  *) echo "✘ Python inesperado en $PY_HOME" >&2; exit 1 ;;
esac
cp -R "$PY_HOME/" "$OUT/python/"
# Salvaguarda: nunca recortar a través de un enlace (borraría la instalación original).
if [ -L "$OUT/python" ] || [ -L "$OUT/python/lib" ]; then
  echo "✘ La copia de Python es un enlace simbólico; se aborta" >&2; exit 1
fi
# Recortes seguros (solo en la COPIA): GUI y herramientas que el backend no usa.
LIB="$OUT/python/lib/python$PY_VERSION"
rm -rf "$LIB/test" "$LIB/idlelib" "$LIB/tkinter" "$LIB/turtledemo" "$LIB/ensurepip" \
       "$LIB/lib2to3" "$OUT/python/share" "$OUT/python/include" \
       "$OUT/python/lib/tcl"* "$OUT/python/lib/tk"* "$OUT/python/lib/itcl"* \
       "$OUT/python/lib/thread"* "$OUT/python/lib/pkgconfig"
find "$OUT/python" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "→ Instalando dependencias de producción"
REQS="$(mktemp)"
(cd "$BACKEND" && uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -q > "$REQS")
uv pip install -q --python "$OUT/python/bin/python3" --target "$OUT/site-packages" -r "$REQS"
rm -f "$REQS"

echo "→ Copiando el código del backend"
rsync -a --exclude "__pycache__" "$BACKEND/app" "$OUT/"

cat > "$OUT/launch.py" <<'EOF'
"""Arranque del backend empaquetado. Se ejecuta con `python -I` (modo aislado): se ignoran
variables PYTHON* y el directorio del usuario, así que las rutas se añaden aquí."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / "site-packages")]

from app.main import main  # noqa: E402

main()
EOF

echo "→ Precompilando bytecode"
"$OUT/python/bin/python3" -I -m compileall -q "$OUT/app" "$OUT/site-packages" >/dev/null

echo "✔ Runtime listo: $(du -sh "$OUT" | cut -f1)"
