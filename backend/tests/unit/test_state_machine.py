"""Meeting state machine (tech spec 5). Pure functions, no database."""

from __future__ import annotations

import pytest

from mosaique.domain.state import (
    InvalidTransition,
    MeetingState,
    accepts_audio,
    cancel,
    complete,
    end,
    fail,
    open_room,
    start,
)


def test_happy_path_reaches_completed():
    s = MeetingState.CREATED
    s = open_room(s)
    assert s is MeetingState.JOINABLE
    s = start(s)
    assert s is MeetingState.LIVE
    s = end(s)
    assert s is MeetingState.FINALIZING
    s = complete(s)
    assert s is MeetingState.COMPLETED


@pytest.mark.parametrize("state", [MeetingState.FINALIZING, MeetingState.COMPLETED])
def test_end_is_idempotent(state):
    assert end(state) is state


def test_end_twice_from_live_yields_one_finalizing():
    first = end(MeetingState.LIVE)
    second = end(first)
    assert first is MeetingState.FINALIZING
    assert second is MeetingState.FINALIZING


@pytest.mark.parametrize(
    "state",
    [MeetingState.CREATED, MeetingState.JOINABLE, MeetingState.CANCELLED, MeetingState.FAILED],
)
def test_end_rejected_from_invalid_states(state):
    with pytest.raises(InvalidTransition):
        end(state)


def test_completed_cannot_return_to_live():
    with pytest.raises(InvalidTransition):
        start(MeetingState.COMPLETED)


def test_cancel_only_before_live():
    assert cancel(MeetingState.CREATED) is MeetingState.CANCELLED
    assert cancel(MeetingState.JOINABLE) is MeetingState.CANCELLED
    with pytest.raises(InvalidTransition):
        cancel(MeetingState.LIVE)


def test_fail_only_from_finalizing():
    assert fail(MeetingState.FINALIZING) is MeetingState.FAILED
    with pytest.raises(InvalidTransition):
        fail(MeetingState.LIVE)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (MeetingState.CREATED, False),
        (MeetingState.JOINABLE, True),
        (MeetingState.LIVE, True),
        (MeetingState.FINALIZING, False),
        (MeetingState.COMPLETED, False),
    ],
)
def test_audio_acceptance_matches_spec(state, expected):
    assert accepts_audio(state) is expected
