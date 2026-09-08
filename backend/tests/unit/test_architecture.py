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
# Slice 5 adds a second outbound client on the intelligence axis. `httpx` is
# not a *transport* in the D-04 sense — it carries nothing inbound — so it gets
# its own rule below rather than joining the set above, which would fail the
# test client in `tests/` for no reason.
HTTP_CLIENT_MODULES = {"httpx", "requests", "aiohttp", "openai"}
# ADR-13 consequence 4: a second runtime is exactly when this test stops being
# theatre. `mlx_runtime.py` now really does import these, so the ban is load
# bearing rather than hypothetical.
MODEL_MODULES = {
    "moshi",
    "torch",
    "transformers",
    "moshi_mlx",
    "mlx",
    "mlx_lm",
    "sentencepiece",
    "huggingface_hub",
}


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


def test_intelligence_does_not_import_an_http_client():
    """The LLM seam, held the same way the ASR one is.

    `intelligence/` owns the prompt, the schema and the vendor translation;
    `llm_runtime/` owns the socket. Without this test the split survives only
    as a convention, and the convenient `import httpx` is one layer away —
    exactly how `moshi-server`'s client would have ended up inside `speech/`.
    """
    offenders = {
        str(path.relative_to(SRC)): sorted(imported_modules(path) & HTTP_CLIENT_MODULES)
        for path in python_files("intelligence")
        if imported_modules(path) & HTTP_CLIENT_MODULES
    }
    assert not offenders, f"an HTTP client leaked into the intelligence layer: {offenders}"


def test_the_llm_adapter_is_reachable_without_its_transport():
    """The property the seam exists for, stated as an import rather than prose.

    If this module can be imported with no HTTP client installed, then the
    OpenAI adapter can be unit-tested without a network or an API key — which
    is the whole reason the translation lives apart from the plumbing.
    """
    module = SRC / "intelligence" / "adapters" / "openai_chat.py"
    assert not (imported_modules(module) & HTTP_CLIENT_MODULES)


def test_the_runtime_depends_on_the_ingress_protocol_not_the_websocket_class():
    runtime = SRC / "realtime" / "sessions" / "meeting.py"
    imports = imported_modules(runtime)
    assert "fastapi" not in imports
    source = runtime.read_text(encoding="utf-8")
    assert "BrowserWebSocketIngress" not in source
    assert "MeetingIngress" in source


def test_fake_and_kyutai_adapters_satisfy_the_same_protocol():
    from mosaique.speech.adapters.fake import FakeRecognizer
    from mosaique.speech.adapters.kyutai import KyutaiRecognizer
    from mosaique.speech.interfaces import StreamingRecognizer

    assert isinstance(FakeRecognizer(), StreamingRecognizer)
    assert isinstance(KyutaiRecognizer(lambda: None), StreamingRecognizer)  # type: ignore[arg-type]


def test_the_kyutai_adapter_does_not_open_its_own_socket():
    """Slice 4's version of the D-04 rule.

    `moshi_server` talks over a WebSocket, which `speech/` may not import. The
    socket lives in `asr_runtime/` and is injected through a Protocol. This is
    the assertion that keeps that arrangement from quietly collapsing back into
    a direct import the first time someone finds the indirection annoying.
    """
    offenders = {
        str(path.relative_to(SRC)): sorted(imported_modules(path) & TRANSPORT_MODULES)
        for path in python_files("speech/adapters/kyutai")
        if imported_modules(path) & TRANSPORT_MODULES
    }
    assert not offenders, f"the ASR adapter opened its own transport: {offenders}"


def test_the_asr_transport_carries_no_model_code():
    """The mirror image: `asr_runtime/` may hold a socket, never a model."""
    offenders = {
        str(path.relative_to(SRC)): sorted(imported_modules(path) & MODEL_MODULES)
        for path in python_files("asr_runtime")
        if imported_modules(path) & MODEL_MODULES
    }
    assert not offenders, f"model libraries leaked into the transport: {offenders}"


def test_mlx_dependencies_are_gated_on_apple_silicon():
    """ADR-13 consequence 5, as a build failure rather than a code review note.

    A plain `moshi_mlx` dependency breaks `uv pip install -e ".[dev]"` on Linux
    and in any future CI, and it breaks it at install time — long before anyone
    reaches a test that would explain why.
    """
    import tomllib

    pyproject = tomllib.loads((SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]

    assert "mlx" in extras, "the MLX runtime must stay an optional extra"
    ungated = [
        requirement
        for requirement in extras["mlx"]
        if "sys_platform == 'darwin'" not in requirement
        or "platform_machine == 'arm64'" not in requirement
    ]
    assert not ungated, f"MLX requirements without a platform marker: {ungated}"


def test_the_default_install_pulls_in_no_model_library():
    """`dev` is what the sandbox and CI install. It must stay model-free."""
    import tomllib

    pyproject = tomllib.loads((SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    installed = (
        pyproject["project"]["dependencies"]
        + (pyproject["project"]["optional-dependencies"]["dev"])
    )

    leaked = [
        requirement
        for requirement in installed
        if any(requirement.lower().startswith(name) for name in MODEL_MODULES)
    ]
    assert not leaked, f"a model library reached the default install: {leaked}"
