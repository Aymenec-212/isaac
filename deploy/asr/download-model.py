"""Download immutable model artifacts and verify size/SHA256 before atomic install."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def valid(path, spec):
    if not path.is_file() or path.stat().st_size != spec["size"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == spec["sha256"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    lock = json.loads(Path(__file__).with_name("model-lock.json").read_text())
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, spec in lock["files"].items():
        dest = args.directory / name
        if valid(dest, spec):
            print(f"Verified {name}")
            continue
        url = f"https://huggingface.co/{lock['repository']}/resolve/{lock['revision']}/{name}"
        part = dest.with_name(dest.name + ".partial")
        try:
            with urllib.request.urlopen(url, timeout=60) as src, part.open("wb") as out:
                while chunk := src.read(1024 * 1024):
                    out.write(chunk)
            if not valid(part, spec):
                raise ValueError(f"Checksum/size mismatch: {name}")
            part.replace(dest)
            print(f"Installed {name}")
        finally:
            part.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
