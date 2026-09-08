"""Deterministic ASR adapter for tests and pre-Kyutai slices."""

from mosaique.speech.adapters.fake.measured import (
    MEASURED_MODEL_DELAY_MS,
    MeasuredASRSession,
    MeasuredRecognizer,
    MeasuredWord,
    load_measured_words,
)
from mosaique.speech.adapters.fake.recognizer import FakeASRSession, FakeRecognizer
from mosaique.speech.adapters.fake.script import (
    DEFAULT_SCRIPT,
    ScriptedEndOfTurn,
    ScriptedWord,
    ScriptItem,
)

__all__ = [
    "DEFAULT_SCRIPT",
    "MEASURED_MODEL_DELAY_MS",
    "MeasuredASRSession",
    "MeasuredRecognizer",
    "MeasuredWord",
    "load_measured_words",
    "FakeASRSession",
    "FakeRecognizer",
    "ScriptItem",
    "ScriptedEndOfTurn",
    "ScriptedWord",
]
