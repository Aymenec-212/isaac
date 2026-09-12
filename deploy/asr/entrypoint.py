"""Inject a file secret into ephemeral config without putting it in argv or logs."""

import json
import os
import re
from pathlib import Path


def render(template: str, key: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key):
        raise ValueError("ASR key must contain 32–128 URL-safe characters")
    marker = "authorized_ids = []"
    if template.count(marker) != 1:
        raise ValueError("Expected exactly one authorization placeholder")
    return template.replace(marker, "authorized_ids = " + json.dumps([key]))


if __name__ == "__main__":
    key = Path("/run/secrets/asr_api_key").read_text().strip()
    rendered = render(Path("/opt/mosaique/config.toml").read_text(), key)
    os.umask(0o077)
    config = Path("/tmp/server.toml")
    config.write_text(rendered)
    os.execvp(
        "moshi-server",
        [
            "moshi-server",
            "worker",
            "--config",
            str(config),
            "--addr",
            "0.0.0.0",
            "--port",
            "8080",
            "--log",
            "warn",
        ],
    )
