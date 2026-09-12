"""Check the opt-in probe's pass/fail gates with a simulated protocol backend."""

from __future__ import annotations

import argparse

import pytest
from tools.remote_asr import __main__ as probe

from mosaique.speech.adapters.kyutai.identity import moshi_server_identity
from mosaique.speech.adapters.kyutai.moshi_server import MoshiSessionError
from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES, WordEvent


@pytest.mark.parametrize("wrong_tail", [False, True])
async def test_probe_requires_both_reference_tails_and_slot_reuse(
    tmp_path, monkeypatch, wrong_tail
):
    instances = []

    class Stub:
        def __init__(self, *args, **kwargs):
            self.index = len(instances)
            instances.append(self)
            self.processed_frames = 0
            self.identity = moshi_server_identity("kyutai/stt-1b-en_fr", "f16")
            self.closed = False

        async def start(self, emit):
            self.emit = emit
            if self.index == 2:
                raise MoshiSessionError("ASR_CAPACITY_EXHAUSTED", "full")

        async def push(self, pcm):
            self.processed_frames += 1

        async def flush(self):
            text = (
                "incorrect"
                if wrong_tail and self.index == 1
                else ["alpha", "bravo"][self.index % 2]
            )
            self.emit(WordEvent(text=text, start_ms=0, end_ms=80))
            self.closed = True

        async def close(self):
            self.closed = True

    async def no_sleep(delay):
        return None

    monkeypatch.setattr(probe, "MoshiServerBackend", Stub)
    monkeypatch.setattr(probe.asyncio, "sleep", no_sleep)
    monkeypatch.setenv("MOSAIQUE_ASR_MOSHI_SERVER_API_KEY", "test-key")
    a, b = tmp_path / "a.pcm", tmp_path / "b.pcm"
    a.write_bytes(bytes(FRAME_PAYLOAD_BYTES))
    b.write_bytes(b"\x01\x00" * (FRAME_PAYLOAD_BYTES // 2))
    args = argparse.Namespace(
        url="ws://localhost", pcm_a=a, pcm_b=b, tail_a="alpha", tail_b="bravo"
    )
    report = {"streams": {}}
    if wrong_tail:
        with pytest.raises(ExceptionGroup):
            await probe.run(args, report)
        assert not report.get("slot_reused")
    else:
        await probe.run(args, report)
        assert report["slot_reused"] and report["third_slot_rejected"]
        assert len(report["streams"]) == 2
    assert all(instance.closed for instance in instances)
