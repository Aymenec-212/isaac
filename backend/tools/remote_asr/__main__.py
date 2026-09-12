"""Run from backend: python -m tools.remote_asr --help. Requires real PCM fixtures."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path

from mosaique.asr_runtime.moshi_ws import MoshiWebSocketTransport
from mosaique.speech.adapters.kyutai.moshi_server import MoshiServerBackend, MoshiSessionError
from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES, ASRErrorEvent, WordEvent


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def fixture(path: Path) -> bytes:
    pcm = path.read_bytes()
    if not pcm or len(pcm) % 2:
        raise ValueError("Fixture must be nonempty s16le 24 kHz mono PCM")
    # Canonical ingress uses full frames; pad the final partial frame with silence.
    return pcm + b"\x00" * (-len(pcm) % FRAME_PAYLOAD_BYTES)


async def run(args: argparse.Namespace, report: dict) -> None:
    inputs = [fixture(args.pcm_a), fixture(args.pcm_b)]
    if inputs[0] == inputs[1]:
        raise ValueError("Use distinct speaker fixtures for attribution evidence")
    key = os.environ["MOSAIQUE_ASR_MOSHI_SERVER_API_KEY"]

    def backend():
        return MoshiServerBackend(
            MoshiWebSocketTransport(args.url, api_key=key), quantization="f16"
        )

    streams = [backend(), backend()]
    seen: list[list] = [[], []]
    try:
        # Stagger connections: global batch step_idx must not affect stream B time.
        await streams[0].start(seen[0].append)
        await asyncio.sleep(0.4)
        await streams[1].start(seen[1].append)
        third = backend()
        try:
            await third.start(lambda event: None)
            raise RuntimeError("Expected the pinned two-slot server to reject stream three")
        except MoshiSessionError as exc:
            if exc.code != "ASR_CAPACITY_EXHAUSTED":
                raise
            report["third_slot_rejected"] = True
        finally:
            await third.close()

        async def feed(index: int, tail: str):
            pcm = inputs[index]
            started = time.monotonic()
            peak_lag_ms = 0
            for offset in range(0, len(pcm), FRAME_PAYLOAD_BYTES):
                frame_index = offset // FRAME_PAYLOAD_BYTES
                await asyncio.sleep(max(0, started + frame_index * 0.08 - time.monotonic()))
                await streams[index].push(pcm[offset : offset + FRAME_PAYLOAD_BYTES])
                peak_lag_ms = max(
                    peak_lag_ms, (frame_index + 1 - streams[index].processed_frames) * 80
                )
            # Keep the last frame at real-time pacing before accelerated drain.
            await asyncio.sleep(max(0, started + len(pcm) / 48000 - time.monotonic()))
            drain_start = time.monotonic()
            await streams[index].flush()
            words = [asdict(e) for e in seen[index] if isinstance(e, WordEvent)]
            text = " ".join(w["text"] for w in words)
            result = {
                "fixture_sha256": hashlib.sha256(pcm).hexdigest(),
                "input_frames": len(pcm) // FRAME_PAYLOAD_BYTES,
                "audio_seconds": len(pcm) / 48000,
                "elapsed_seconds": time.monotonic() - started,
                "drain_seconds": time.monotonic() - drain_start,
                "peak_lag_ms": peak_lag_ms,
                "processed_frames": streams[index].processed_frames,
                "asr_version": streams[index].identity.asr_version,
                "words": words,
                "expected_tail": tail,
                "tail_present": bool(words) and normalize(text).endswith(normalize(tail)),
                "errors": [asdict(e) for e in seen[index] if isinstance(e, ASRErrorEvent)],
            }
            report["streams"][str(index)] = result
            if not result["tail_present"] or result["errors"]:
                raise RuntimeError("Transcript tail or error gate failed")
            if not words or streams[index].processed_frames < len(pcm) // FRAME_PAYLOAD_BYTES:
                raise RuntimeError("No independent inference progress")

        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(feed(0, args.tail_a))
            tasks.create_task(feed(1, args.tail_b))
        # Confirm a released slot accepts fresh inference, without old timestamps.
        reused = backend()
        try:
            await reused.start(lambda event: None)
            await reused.push(b"\x00" * FRAME_PAYLOAD_BYTES)
            await reused.flush()
            if reused.processed_frames == 0:
                raise RuntimeError("Reused slot did not progress")
            report["slot_reused"] = True
        finally:
            await reused.close()
    finally:
        await asyncio.gather(*(stream.close() for stream in streams))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", required=True, help="Private/tunneled base ws:// URL, no key in URL"
    )
    parser.add_argument("--pcm-a", required=True, type=Path)
    parser.add_argument("--pcm-b", required=True, type=Path)
    parser.add_argument("--tail-a", required=True, help="Reference final phrase in fixture A")
    parser.add_argument("--tail-b", required=True, help="Reference final phrase in fixture B")
    parser.add_argument(
        "--deployment-record",
        required=True,
        type=Path,
        help="Sanitized operator JSON: image_digest, moshi_revision, model_revision, GPU, driver",
    )
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if "?" in args.url or "@" in args.url:
        parser.error("Do not put credentials in the URL; use the API-key environment variable")
    if not normalize(args.tail_a) or not normalize(args.tail_b):
        parser.error("Reference tails must contain words")
    record = json.loads(args.deployment_record.read_text())
    for field in ["image_digest", "moshi_revision", "model_revision", "gpu", "driver"]:
        if not record.get(field):
            parser.error(f"Missing deployment provenance: {field}")
    if not re.search(r"sha256:[0-9a-f]{64}$", record["image_digest"]):
        parser.error("Provide the deployed immutable image digest")
    if record["moshi_revision"] != "e6a55d2722a65870ef52a6c9f6ecfc0e90f38362":
        parser.error("This probe targets the R1-pinned moshi revision")
    if record["model_revision"] != "095e38f6242006a93c2541149b181988397f5c7c":
        parser.error("This probe targets the R1-pinned model revision")
    if record.get("lm_dtype") != "f16":
        parser.error("Confirm deployed lm_dtype=f16; precision cannot be inferred from the wire")
    record = {
        k: record[k]
        for k in ["image_digest", "moshi_revision", "model_revision", "gpu", "driver", "lm_dtype"]
    }
    report: dict = {
        "runtime": "real-moshi-server",
        "status": "failed",
        "provenance": record,
        "streams": {},
        "speed": 1.0,
    }
    try:
        asyncio.run(run(args, report))
        report["status"] = "passed"
    except BaseException as exc:
        # Do not leak URLs, headers, server payloads or API keys into failure text.
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
