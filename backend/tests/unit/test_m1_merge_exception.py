"""The human merge exception must fail closed and stay opt-in/visible."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from tools.m1_merge_exception import ASSERTION, NODE

pytest_plugins = ("pytester",)


@pytest.mark.parametrize(
    ("case", "enabled", "exit_code", "outcomes"),
    [
        ("baseline", True, 0, {"xfailed": 1}),
        ("baseline", False, 1, {"failed": 1}),
        ("pass", True, 1, {"failed": 1}),
        ("other_assertion", True, 1, {"failed": 1}),
        ("runtime_error", True, 1, {"failed": 1}),
        ("setup_error", True, 1, {"errors": 1}),
        ("teardown_error", True, 1, {"xfailed": 1, "errors": 1}),
        ("other_test_failure", True, 1, {"xfailed": 1, "failed": 1}),
        ("missing", True, 4, None),
        ("duplicate", True, 4, None),
    ],
)
def test_exception_policy(pytester, monkeypatch, case, enabled, exit_code, outcomes):
    # Keep subprocesses separate from the real integration fixtures/DB and make
    # the opt-in plugin importable before conftest discovery.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    pytester.makeini("[pytest]")
    body = {
        "pass": "pass",
        "other_assertion": 'assert False, "new assertion failure"',
        "runtime_error": 'raise RuntimeError("new runtime failure")',
    }.get(case, ASSERTION)
    source = (
        "from types import SimpleNamespace\n"
        "import pytest\n\n"
        f"def {NODE.split('::')[1]}():\n"
        '    silent = {"participant": {"id": "silent"}}\n'
        '    runtime = SimpleNamespace(_sessions={"silent": object()})\n'
        f"    {body}\n"
    )
    if case == "missing":
        source = "def test_another_test(): pass\n"
    if case == "setup_error":
        source += (
            "\n@pytest.fixture(autouse=True)\n"
            "def broken_setup(): raise RuntimeError('setup failed')\n"
        )
    if case == "teardown_error":
        source += (
            "\n@pytest.fixture(autouse=True)\n"
            "def broken_teardown():\n    yield\n    raise RuntimeError('teardown failed')\n"
        )
    if case == "other_test_failure":
        source += "\ndef test_new_regression(): assert False\n"
    pytester.makepyfile(**{NODE.split("::")[0].removesuffix(".py"): source})
    args = ["-p", "tools.m1_merge_exception"] if enabled else []
    if case == "duplicate":
        args += ["--keep-duplicates", NODE.split("::")[0], NODE.split("::")[0]]
    result = pytester.runpytest_subprocess(
        *args, "-q", "-rxXs", "--junitxml=report.xml", timeout=30
    )
    assert result.ret == exit_code
    if outcomes is not None:
        result.assert_outcomes(**outcomes)
    if enabled and case == "baseline":
        result.stdout.fnmatch_lines(["*XFAIL*M2-ASR-001*"])
        skipped = ET.parse(pytester.path / "report.xml").findall(".//testcase/skipped")
        assert len(skipped) == 1
        assert skipped[0].get("type") == "pytest.xfail"
        assert "M2-ASR-001" in skipped[0].get("message", "")
    if case == "pass":
        result.stdout.fnmatch_lines(["*XPASS(strict)*M2-ASR-001*"])
