"""Exporta el esquema OpenAPI (solo desarrollo) para generar los tipos TypeScript.

Uso: python -m app.export_openapi ../app/src/lib/api/openapi.json
"""

import json
import sys
from pathlib import Path

from app.api.app import create_app
from app.core.config import Settings


def main() -> None:
    out = Path(sys.argv[1])
    dummy = Settings(
        data_dir=Path("/nonexistent"), socket_path=Path("/nonexistent"), token="x" * 32
    )
    schema = create_app(dummy).openapi()
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OpenAPI exportado a {out}")


if __name__ == "__main__":
    main()
