"""Boundary rules, enforced by the build rather than by code review.

Two seams matter enough to fail CI over:

* blueprint D-04 — nothing downstream of the ingress may import a transport type;
* tech spec 9.1 — nothing outside the Kyutai adapter may import model types.

Both are checked by reading the source, so they hold even for code paths no
test happens to execute.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "mosaique"

# Layers that must remain ignorant of how audio arrived.
DOWNSTREAM_OF_INGRESS = [
    "domain",
    "transcript",
    "intelligence",
    "persistence",
    "jobs",
    "speech",
    "realtime/sessions",
    "realtime/ingress",
]

TRANSPORT_MODULES = {"fastapi", "starlette", "websockets", "uvicorn"}
MODEL_MODULES = {"moshi", "torch", "transformers", "moshi_mlx"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def python_files(relative: str) -> list[Path]:
    return sorted((SRC / relative).rglob("*.py"))


@pytest.mark.parametrize("layer", DOWNSTREAM_OF_INGRESS)
def test_nothing_downstream_of_the_ingress_imports_transport(layer):
    """The rule that makes the ingress seam worth having (blueprint D-04)."""
    offenders = {
        str(path.relative_to(SRC)): sorted(imported_modules(path) & TRANSPORT_MODULES)
        for path in python_files(layer)
        if imported_modules(path) & TRANSPORT_MODULES
    }
    assert not offenders, f"transport types leaked past the ingress seam: {offenders}"


def test_only_the_kyutai_adapter_may_import_model_libraries():
    """Tech spec 9.1: model types stay behind StreamingRecognizer."""
    offenders = {}
    for path in SRC.rglob("*.py"):
        if "adapters/kyutai" in path.as_posix():
            continue
        leaked = imported_modules(path) & MODEL_MODULES
        if leaked:
            offenders[str(path.relative_to(SRC))] = sorted(leaked)
    assert not offenders, f"model libraries leaked out of the adapter: {offenders}"


def test_the_runtime_depends_on_the_ingress_protocol_not_the_websocket_class():
    runtime = SRC / "realtime" / "sessions" / "meeting.py"
    imports = imported_modules(runtime)
    assert "fastapi" not in imports
    source = runtime.read_text(encoding="utf-8")
    assert "BrowserWebSocketIngress" not in source
    assert "MeetingIngress" in source


def test_fake_and_kyutai_adapters_satisfy_the_same_protocol():
    from mosaique.speech.adapters.fake import FakeRecognizer
    from mosaique.speech.interfaces import StreamingRecognizer

    assert isinstance(FakeRecognizer(), StreamingRecognizer)
