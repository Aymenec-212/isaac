"""Deterministic ASR adapter for tests and pre-Kyutai slices."""

from mosaique.speech.adapters.fake.recognizer import FakeASRSession, FakeRecognizer
from mosaique.speech.adapters.fake.script import (
    DEFAULT_SCRIPT,
    ScriptedEndOfTurn,
    ScriptedWord,
    ScriptItem,
)

__all__ = [
    "DEFAULT_SCRIPT",
    "FakeASRSession",
    "FakeRecognizer",
    "ScriptItem",
    "ScriptedEndOfTurn",
    "ScriptedWord",
]
