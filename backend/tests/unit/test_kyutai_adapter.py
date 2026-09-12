"""The Kyutai adapter, on a machine that cannot run Kyutai.

Everything here uses a fake backend or a fake transport. What is covered is the
part that is the same whichever runtime is underneath — identity, health, the
liveness check, word assembly, the reconnect schedule, the moshi-server message
translation — which is also the part that is worth testing without the model.

What is *not* covered, and is marked IMPLEMENTED rather than VERIFIED in
`PROJECT_STATE.md`: `mlx_runtime.py` (needs Apple silicon) and
`asr_runtime/moshi_ws.py` (needs a CUDA host running moshi-server).
"""

from __future__ import annotations

import asyncio
import random

import pytest

from mosaique.speech.adapters.kyutai import (
    KyutaiRecognizer,
    KyutaiSession,
    MoshiServerBackend,
    PieceAssembler,
    delays,
    mlx_identity,
    model_id_from_repo,
    moshi_server_identity,
    quantization_from_weights,
)
from mosaique.speech.adapters.kyutai.backend import EventSink
from mosaique.speech.adapters.kyutai.transport import Message, TransportClosed
from mosaique.speech.interfaces import (
    FRAME_PAYLOAD_BYTES,
    ASRErrorEvent,
    AsrIdentity,
    ASRSession,
    ASRSessionConfig,
    AudioChunk,
    EndOfTurnEvent,
    StreamingRecognizer,
    WordEvent,
)

FRAME = b"\x00" * FRAME_PAYLOAD_BYTES


# --------------------------------------------------------------------------
# Identity — ADR-13 consequence 3
# --------------------------------------------------------------------------


def test_asr_version_names_the_model_the_runtime_and_the_precision():
    """The exact string Spike B1 measured, not the ADR's guessed example."""
    assert (
        mlx_identity("kyutai/stt-1b-en_fr-mlx", "model.safetensors").asr_version
        == "kyutai/stt-1b-en_fr@mlx-bf16"
    )


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ("model.q4.safetensors", "q4"),
        ("model.q8.safetensors", "q8"),
        ("model.safetensors", "bf16"),
    ],
)
def test_quantization_is_read_the_way_the_loader_reads_it(weights, expected):
    assert quantization_from_weights(weights) == expected


@pytest.mark.parametrize(
    "repo", ["kyutai/stt-1b-en_fr-mlx", "kyutai/stt-1b-en_fr-candle", "kyutai/stt-1b-en_fr"]
)
def test_the_runtime_suffix_never_leaks_into_the_model_id(repo):
    assert model_id_from_repo(repo) == "kyutai/stt-1b-en_fr"


def test_two_runtimes_of_one_model_are_never_the_same_version():
    """A-16 is unresolved, so the two must stay distinguishable in the data."""
    mlx = mlx_identity("kyutai/stt-1b-en_fr-mlx", "model.safetensors")
    cuda = moshi_server_identity("kyutai/stt-1b-en_fr", "bf16")

    assert mlx.model_id == cuda.model_id
    assert mlx.asr_version != cuda.asr_version


def test_the_version_string_always_fits_the_column():
    identity = AsrIdentity(model_id="x" * 200, runtime="mlx", quantization="bf16")

    assert len(identity.truncated()) == 80


# --------------------------------------------------------------------------
# Piece assembly — B1 §4
# --------------------------------------------------------------------------


def test_pieces_become_whole_words_at_the_next_word_marker():
    assembler = PieceAssembler(delay_ms=500)

    assert assembler.on_piece(10, "▁budget") == []
    emitted = assembler.on_piece(14, "▁trimes")

    assert [w.text for w in emitted] == ["budget"]
    assert assembler.on_piece(15, "triel") == []
    assert [w.text for w in assembler.flush()] == ["trimestriel"]


def test_a_word_is_timed_back_to_when_it_was_spoken():
    """The token arrives `delay_ms` after the audio it describes (ADR-11)."""
    assembler = PieceAssembler(delay_ms=500)
    assembler.on_piece(20, "▁vendredi")

    [word] = assembler.flush()

    assert (word.start_ms, word.end_ms) == (20 * 80 - 500, 21 * 80 - 500)


def test_a_word_never_lands_before_the_stream_started():
    assembler = PieceAssembler(delay_ms=500)
    assembler.on_piece(1, "▁oui")

    assert assembler.flush()[0].start_ms == 0


def test_a_bare_word_marker_does_not_become_an_empty_word():
    assembler = PieceAssembler(delay_ms=0)
    assembler.on_piece(1, "▁")

    assert assembler.flush() == []


def test_flushing_twice_does_not_repeat_the_word():
    assembler = PieceAssembler(delay_ms=0)
    assembler.on_piece(1, "▁oui")

    assert len(assembler.flush()) == 1
    assert assembler.flush() == []


# --------------------------------------------------------------------------
# Reconnect schedule — tech spec 9.2
# --------------------------------------------------------------------------


def test_the_reconnect_schedule_is_bounded():
    """Bounded is the property. A stream retrying forever reads as healthy
    while transcribing nothing, which is the failure this prevents."""
    assert len(list(delays(rng=random.Random(0)))) == 3


def test_the_schedule_backs_off_and_never_exceeds_the_cap():
    observed = [list(delays(rng=random.Random(seed))) for seed in range(25)]

    for schedule in observed:
        assert schedule[0] < schedule[-1]
        assert all(0.0 <= d <= 4.0 for d in schedule)


def test_jitter_stops_a_fleet_reconnecting_in_lockstep():
    first = [list(delays(rng=random.Random(seed)))[0] for seed in range(20)]

    assert len(set(first)) > 1


# --------------------------------------------------------------------------
# Session — health, liveness, the seam
# --------------------------------------------------------------------------


class StubBackend:
    """A backend that does nothing until a test tells it to."""

    def __init__(self, *, emits_end_of_turn: bool = False, delay_ms: int = 500) -> None:
        self._identity = AsrIdentity("kyutai/stt-1b-en_fr", "stub", "none")
        self._delay_ms = delay_ms
        self._emits = emits_end_of_turn
        self.processed_frames = 0
        self.pushed: list[bytes] = []
        self.flushed = 0
        self.closed = False
        self.emit: EventSink | None = None

    @property
    def identity(self) -> AsrIdentity:
        return self._identity

    @property
    def delay_ms(self) -> int:
        return self._delay_ms

    @property
    def emits_end_of_turn(self) -> bool:
        return self._emits

    async def start(self, emit: EventSink) -> None:
        self.emit = emit

    async def push(self, pcm: bytes) -> None:
        self.pushed.append(pcm)

    async def flush(self) -> None:
        self.flushed += 1

    async def close(self) -> None:
        self.closed = True

    def transcribe(self, frames: int = 1) -> None:
        self.processed_frames += frames


async def open_session(**kwargs) -> tuple[KyutaiSession, StubBackend]:
    backend = StubBackend(**kwargs)
    session = KyutaiSession(backend, liveness_timeout_s=0.05)
    await session.start()
    return session, backend


async def test_the_kyutai_session_is_an_asr_session():
    session, _ = await open_session()

    assert isinstance(session, ASRSession)


async def test_the_recognizer_is_a_streaming_recognizer():
    recognizer = KyutaiRecognizer(StubBackend)

    assert isinstance(recognizer, StreamingRecognizer)
    session = await recognizer.open_session(ASRSessionConfig())
    assert recognizer.identity == session.identity


async def test_lag_is_audio_handed_over_that_the_model_has_not_reached():
    session, backend = await open_session()
    for i in range(5):
        await session.push_audio(AudioChunk(pcm=FRAME, sequence=i))
    backend.transcribe(2)

    assert session.health().lag_ms == 3 * 80


async def test_transcribed_offset_follows_frames_processed_not_frames_pushed():
    """The distinction the ADR-11 bug was about, now measurable.

    At 1.24x realised the MLX worker really does fall behind, so a
    `transcribed_offset_ms` built on pushed audio would run ahead of the
    transcript and the segmenter would invent silences.
    """
    session, backend = await open_session(delay_ms=500)
    for i in range(50):
        await session.push_audio(AudioChunk(pcm=FRAME, sequence=i))

    assert session.health().transcribed_offset_ms == 0  # nothing processed yet
    backend.transcribe(20)
    assert session.health().transcribed_offset_ms == 20 * 80 - 500


async def test_a_recognizer_that_stops_consuming_is_reported_not_hidden():
    """Tech spec 9.2's ASR_TIMEOUT, measured on progress rather than on events.

    Taken literally — "no event for 5 s" — this would fire on any speaker who
    pauses, because most MLX steps emit nothing at all (663 of B1's 825).
    """
    session, backend = await open_session()
    await session.push_audio(AudioChunk(pcm=FRAME, sequence=0))
    backend.transcribe()
    await session.push_audio(AudioChunk(pcm=FRAME, sequence=1))
    await asyncio.sleep(0.06)
    await session.push_audio(AudioChunk(pcm=FRAME, sequence=2))

    events = session.events()
    event = await asyncio.wait_for(anext(events), timeout=1)

    assert isinstance(event, ASRErrorEvent)
    assert event.code == "ASR_TIMEOUT"
    assert not event.fatal
    assert not session.health().healthy


async def test_silence_alone_is_never_reported_as_a_stalled_recognizer():
    """The whole point of the deviation above: a quiet speaker is not a fault."""
    session, backend = await open_session()
    for i in range(20):
        await session.push_audio(AudioChunk(pcm=FRAME, sequence=i))
        backend.transcribe()
        await asyncio.sleep(0.01)

    assert session.health().healthy
    assert session._queue.empty()


async def test_health_counts_events_so_the_runtime_knows_when_it_has_caught_up():
    """`_read_events` only ticks silence when emitted == consumed."""
    session, backend = await open_session()
    assert backend.emit is not None
    backend.emit(WordEvent(text="bonjour", start_ms=0, end_ms=200))
    backend.emit(WordEvent(text="tout", start_ms=300, end_ms=400))

    assert session.health().events_emitted == 2


async def test_closing_ends_the_event_stream():
    session, backend = await open_session()
    events = session.events()
    await session.close()

    with pytest.raises(StopAsyncIteration):
        await anext(events)
    assert backend.closed
    with pytest.raises(RuntimeError):
        await session.push_audio(AudioChunk(pcm=FRAME, sequence=0))


async def test_flush_is_delegated_to_the_runtime_that_knows_what_it_costs():
    session, backend = await open_session()
    await session.flush()

    assert backend.flushed == 1


# --------------------------------------------------------------------------
# moshi-server protocol translation — no server, no CUDA, no network
# --------------------------------------------------------------------------


class FakeTransport:
    """Scripted server messages in, sent messages recorded."""

    def __init__(self, inbound: list[Message] | None = None) -> None:
        self.sent: list[Message] = []
        self._inbound: asyncio.Queue[Message] = asyncio.Queue()
        self._inbound.put_nowait({"type": "Ready"})
        for message in inbound or []:
            self._inbound.put_nowait(message)
        self.connects = 0
        self.closed = False
        self.fail_sends = 0

    async def connect(self) -> None:
        self.connects += 1

    async def send(self, message: Message) -> None:
        if self.fail_sends > 0:
            self.fail_sends -= 1
            raise TransportClosed("peer went away")
        self.sent.append(message)

    async def receive(self) -> Message:
        return await self._inbound.get()

    async def close(self) -> None:
        self.closed = True

    def server_says(self, message: Message) -> None:
        self._inbound.put_nowait(message)


async def moshi_backend(inbound=None) -> tuple[MoshiServerBackend, FakeTransport, list]:
    transport = FakeTransport(inbound)
    backend = MoshiServerBackend(transport)
    seen: list = []
    await backend.start(seen.append)
    return backend, transport, seen


async def settle() -> None:
    for _ in range(6):
        await asyncio.sleep(0)


async def test_a_word_is_held_until_its_end_time_arrives():
    """Emitting early would mean an end_ms a later message contradicts, and a
    contradicted field is a retraction by another name (X-14)."""
    backend, transport, seen = await moshi_backend()
    transport.server_says({"type": "Word", "text": "bonjour", "start_time": 1.5})
    await settle()

    assert seen == []

    transport.server_says({"type": "EndWord", "stop_time": 1.9})
    await settle()

    assert seen == [WordEvent(text="bonjour", start_ms=1500, end_ms=1900, confidence=None)]
    await backend.close()


async def test_a_word_whose_end_never_comes_is_still_emitted():
    backend, transport, seen = await moshi_backend()
    transport.server_says({"type": "Word", "text": "bonjour", "start_time": 1.0})
    transport.server_says({"type": "Word", "text": "tout", "start_time": 1.4})
    await settle()

    assert [w.text for w in seen] == ["bonjour"]
    assert seen[0].end_ms is None
    await backend.close()


async def test_the_step_vad_signal_becomes_an_end_of_turn_event():
    """Where §9.3's `end_of_turn_threshold` stops being dead code.

    On MLX no such event exists at all, which is why the segmenter grew a
    punctuation rule. Here it does — and this is where the 0.5 guess finally
    becomes measurable, once a CUDA host exists (Spike B2).
    """
    backend, transport, seen = await moshi_backend()
    transport.server_says({"type": "Step", "prs": [0.01, 0.02, 0.87, 0.99]})
    await settle()

    assert [type(e) for e in seen] == [EndOfTurnEvent]
    assert seen[0].probability == pytest.approx(0.87)
    await backend.close()


async def test_a_server_build_without_a_vad_field_simply_produces_no_events():
    backend, transport, seen = await moshi_backend()
    transport.server_says({"type": "Step"})
    await settle()

    assert seen == []
    assert backend.processed_frames == 1
    await backend.close()


async def test_audio_is_sent_as_the_float_pcm_the_server_expects():
    backend, transport, _ = await moshi_backend()
    await backend.push(b"\x00\x40" * 1920)

    [message] = transport.sent
    assert message["type"] == "Audio"
    assert len(message["pcm"]) == 1920
    assert message["pcm"][0] == pytest.approx(16384 / 32768)
    await backend.close()


async def test_flush_sends_a_marker_and_waits_for_it_to_come_back():
    """D-05 expressed in the protocol: everything before the marker is done."""
    backend, transport, _ = await moshi_backend()
    flushing = asyncio.create_task(backend.flush())
    await settle()

    assert {"type": "Marker", "id": 1} in transport.sent
    assert not flushing.done()

    transport.server_says({"type": "Marker", "id": 1})
    await asyncio.wait_for(flushing, timeout=1)
    await backend.close()


async def test_a_dropped_connection_requires_a_fresh_session_without_replay():
    from mosaique.speech.adapters.kyutai.moshi_server import MoshiSessionError

    backend, transport, seen = await moshi_backend()
    transport.fail_sends = 1
    with pytest.raises(MoshiSessionError, match="fresh session"):
        await backend.push(FRAME)
    assert transport.connects == 1
    assert transport.closed
    assert transport.sent == []
    assert [e.code for e in seen] == ["ASR_UNAVAILABLE"]
    assert seen[0].fatal
    await backend.close()


# --------------------------------------------------------------------------
# The capability the segmenter branches on
# --------------------------------------------------------------------------


def test_every_recognizer_declares_whether_it_emits_an_end_of_turn():
    """It is on the Protocol, not discovered with `getattr`, because the
    default a missing attribute would take is a segmentation decision."""
    from mosaique.speech.adapters.fake import FakeASRSession

    assert FakeASRSession().emits_end_of_turn is True
    assert KyutaiSession(StubBackend(emits_end_of_turn=False)).emits_end_of_turn is False
    assert KyutaiSession(StubBackend(emits_end_of_turn=True)).emits_end_of_turn is True
