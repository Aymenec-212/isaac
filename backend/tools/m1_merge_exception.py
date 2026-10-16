"""Opt-in M1 merge exception; remove with M2-ASR-001. Never skips test execution.

Load explicitly with ``pytest -p tools.m1_merge_exception ... -rxXs``. Ordinary
pytest runs retain the baseline failure. Only the known allocation assertion in
one exact node may XFAIL; a pass or any other failure remains fatal.
"""

import linecache
from pathlib import Path

import pytest

NODE = (
    "tests/realtime/test_idle_and_pause.py::"
    "test_a_silent_participant_does_not_claim_the_recognizer_stream"
)
REASON = "Human-approved M1 baseline exception; M2-ASR-001; see docs/QUALITY_GATES.md"
ASSERTION = 'assert silent["participant"]["id"] not in runtime._sessions'


def _known_allocation_failure(error: BaseException) -> bool:
    traceback = error.__traceback__
    if traceback is None:
        return False
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    code = traceback.tb_frame.f_code
    return (
        code.co_name == NODE.split("::")[1]
        and Path(code.co_filename).as_posix().endswith("/" + NODE.split("::")[0])
        and linecache.getline(code.co_filename, traceback.tb_lineno).split("#", 1)[0].strip()
        == ASSERTION
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    matches = [item for item in items if item.nodeid == NODE]
    if len(matches) != 1:
        raise pytest.UsageError(f"M1 exception requires exactly one {NODE}; found {len(matches)}")
    matches[0].add_marker(
        pytest.mark.xfail(
            reason=REASON,
            strict=True,
            run=True,
            raises=pytest.RaisesExc(AssertionError, check=_known_allocation_failure),
        )
    )
