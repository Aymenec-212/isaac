"""Scripted French dialogue for the fake recognizer.

Timings are offsets into the participant's ASR stream, so a replay at 10x speed
produces exactly the same transcript as one at real time. That determinism is
the whole point: it is what makes the product path testable before Kyutai.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptedWord:
    at_ms: int
    text: str


@dataclass(frozen=True)
class ScriptedEndOfTurn:
    at_ms: int
    probability: float


ScriptItem = ScriptedWord | ScriptedEndOfTurn


def _phrase(start_ms: int, words: list[str], *, gap_ms: int = 260) -> list[ScriptItem]:
    items: list[ScriptItem] = [
        ScriptedWord(at_ms=start_ms + i * gap_ms, text=w) for i, w in enumerate(words)
    ]
    items.append(ScriptedEndOfTurn(at_ms=start_ms + len(words) * gap_ms, probability=0.9))
    return items


# A short French planning conversation. Enough turns to exercise segment
# closing by end-of-turn, and enough content for the fake summarizer to have
# decisions and actions to point at.
DEFAULT_SCRIPT: list[ScriptItem] = [
    *_phrase(600, ["Bonjour,", "je", "pense", "qu'on", "peut", "commencer."]),
    *_phrase(3200, ["Le", "budget", "du", "trimestre", "est", "validé."]),
    *_phrase(6400, ["Il", "faut", "livrer", "la", "maquette", "avant", "vendredi."]),
    *_phrase(10200, ["Sarah", "s'occupe", "de", "la", "relecture", "du", "contrat."]),
    *_phrase(14400, ["On", "se", "revoit", "lundi", "prochain."]),
]
