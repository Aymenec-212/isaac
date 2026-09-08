"""CLI for the replay harness.

    # against a server started with `uv run uvicorn ... --port 8000`
    uv run python -m tools.replay run scenarios/two-participants.json \
        --host-token "$(uv run python -m mosaique.app.seed | tail -1)" \
        --speed 10 --report /tmp/replay.json

    # write a fixture a scenario can point at
    uv run python -m tools.replay make-fixture out.pcm --ms 20000 --seed 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from tools.replay.fixtures import synthetic_pcm, wav_to_canonical_pcm
from tools.replay.harness import ReplayHarness
from tools.replay.scenario import Scenario


def _run(args: argparse.Namespace) -> int:
    scenario = Scenario.load(Path(args.scenario))
    harness = ReplayHarness(
        base_url=args.base_url,
        host_token=args.host_token,
        scenario=scenario,
        speed=args.speed,
    )
    report = asyncio.run(harness.run())
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    totals = report.totals
    consistent = (
        report.broadcast_reached_every_socket
        and report.views_identical
        and report.finals_all_persisted
    )
    print(
        f"{totals['segments']} segments from {len(report.participants)} participants "
        f"at {report.speed}x ({totals['speedup']}x realised); "
        f"{report.sockets} sockets consistent: {consistent}",
        file=sys.stderr,
    )
    return 0 if report.segments and consistent else 1


def _make_fixture(args: argparse.Namespace) -> int:
    Path(args.out).write_bytes(synthetic_pcm(args.ms, seed=args.seed))
    print(f"wrote {args.ms} ms of 24 kHz s16le mono to {args.out}", file=sys.stderr)
    return 0


def _convert(args: argparse.Namespace) -> int:
    pcm = wav_to_canonical_pcm(Path(args.wav))
    Path(args.out).write_bytes(pcm)
    seconds = len(pcm) / (24_000 * 2)
    print(f"wrote {seconds:.2f} s of 24 kHz s16le mono to {args.out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.replay", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="replay a scenario against a running app-server")
    run.add_argument("scenario", help="path to the scenario JSON")
    run.add_argument("--base-url", default="http://localhost:8000")
    run.add_argument(
        "--host-token", required=True, help="host token; `mosaique.app.seed` prints one"
    )
    run.add_argument("--speed", type=float, default=None, help="override the scenario speed factor")
    run.add_argument("--report", default=None, help="write the JSON report here instead of stdout")
    run.set_defaults(func=_run)

    fixture = sub.add_parser("make-fixture", help="write a deterministic synthetic PCM fixture")
    fixture.add_argument("out")
    fixture.add_argument("--ms", type=int, default=20_000)
    fixture.add_argument("--seed", type=int, default=1)
    fixture.set_defaults(func=_make_fixture)

    convert = sub.add_parser("convert", help="24 kHz mono WAV -> the raw PCM a scenario points at")
    convert.add_argument("wav")
    convert.add_argument("out")
    convert.set_defaults(func=_convert)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
