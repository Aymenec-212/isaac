import asyncio
import os
import wave

import pytest

from mosaique.realtime.protocol.frames import encode_frame
from mosaique.realtime.runtime_state import init_registry, shutdown_registry
from mosaique.speech.adapters.kyutai.mlx_runtime import MlxBackend
from mosaique.speech.adapters.kyutai.session import KyutaiRecognizer
from tests.integration.test_meeting_flow import auth, create_and_join
from tests.realtime.test_reconnect import hello

pytestmark = pytest.mark.skipif(
    not os.environ.get("MOSAIQUE_MLX_TEST_WAV"), reason="opt-in real MLX speech test"
)


@pytest.fixture
async def runtime(engine, tmp_path):
    recognizer = KyutaiRecognizer(MlxBackend)
    await recognizer.preload()
    init_registry(recognizer=recognizer, audio_root=tmp_path / "audio")
    yield recognizer
    await shutdown_registry()


async def test_real_speech_through_gateway_and_persistence(ws_client, settings, tenants):
    with wave.open(os.environ["MOSAIQUE_MLX_TEST_WAV"]) as source:
        assert (source.getnchannels(), source.getsampwidth(), source.getframerate()) == (
            1,
            2,
            24000,
        )
        pcm = source.readframes(source.getnframes()) + bytes(24000 * 2 * 2)
    for attempt in (1, 2):
        token, mid, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
        messages = []
        async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as ws:
            await hello(ws, joined["session_token"])
            await asyncio.sleep(6)  # A quiet join must not count as stalled inference.
            for seq, offset in enumerate(range(0, len(pcm), 3840)):
                await ws.send_bytes(
                    encode_frame(seq, seq * 80, pcm[offset : offset + 3840].ljust(3840, b"\0"))
                )
                await asyncio.sleep(0.08)
                messages.extend(ws.drain())
            result = await ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
            assert result.status_code == 200, result.text
            messages.extend(ws.drain())
        errors = [
            m
            for m in messages
            if m.get("code", "").startswith("ASR_") or m.get("status") == "unavailable"
        ]
        assert not errors, errors
        live_text = [
            m["text"]
            for m in messages
            if m["type"] in ("transcript.delta", "transcript.segment.final")
            and m.get("status") != "gap"
        ]
        assert live_text, messages
        response = await ws_client.http.get(f"/meetings/{mid}/transcript", headers=auth(token))
        segments = response.json()["segments"]
        text = " ".join(s["text"] for s in segments if s.get("status") != "gap")
        assert "bonjour" in text.lower(), text
        assert not any(s.get("status") == "gap" for s in segments), segments
        print(f"PASS real MLX meeting {attempt}: {text}", flush=True)
