"""Dump the OpenAPI schema so the frontend client can be generated from it.

Run from backend/:  uv run python tools/export_openapi.py ../frontend/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mosaique.app.main import create_app


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    schema = create_app().openapi()
    target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
