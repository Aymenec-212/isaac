"""Bounded reconnect schedule (tech spec 9.2).

"3 attempts, 0.5 s -> 4 s with jitter". Pure and separated from the socket that
uses it so the schedule can be asserted rather than described: a backoff that
silently retries forever is the failure mode this exists to prevent, and it is
invisible in an integration test that happens to reconnect on the first try.
"""

from __future__ import annotations

import random
from collections.abc import Iterator

MAX_ATTEMPTS = 3
BASE_DELAY_S = 0.5
MAX_DELAY_S = 4.0
JITTER = 0.25


def delays(
    *,
    attempts: int = MAX_ATTEMPTS,
    base_s: float = BASE_DELAY_S,
    max_s: float = MAX_DELAY_S,
    jitter: float = JITTER,
    rng: random.Random | None = None,
) -> Iterator[float]:
    """Yield one delay per retry: exponential, capped, jittered, and finite.

    Jitter is multiplicative and one-sided-symmetric around the nominal delay,
    so a fleet of streams reconnecting after the same outage does not arrive in
    lockstep. It never extends past `max_s`.
    """
    source = rng or random.Random()
    for attempt in range(attempts):
        nominal = min(base_s * (2**attempt), max_s)
        spread = nominal * jitter
        yield max(0.0, min(max_s, source.uniform(nominal - spread, nominal + spread)))
