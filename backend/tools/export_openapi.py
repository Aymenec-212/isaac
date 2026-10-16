"""Dump the OpenAPI schema so the frontend client can be generated from it.

Run from backend/:  uv run python tools/export_openapi.py ../frontend/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mosaique.app.main import create_app
from mosaique.config.settings import get_settings


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    mode = sys.argv[2] if len(sys.argv) > 2 else "prototype"
    if mode not in ("prototype", "enterprise"):
        raise ValueError("mode must be prototype or enterprise")
    settings = get_settings().model_copy(update={"application_mode": mode})
    schema = create_app(settings).openapi()
    target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
