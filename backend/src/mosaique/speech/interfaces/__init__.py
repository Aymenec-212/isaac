"""Speech interfaces."""

from mosaique.speech.interfaces.asr import (
    BYTES_PER_SAMPLE,
    FRAME_DURATION_MS,
    FRAME_PAYLOAD_BYTES,
    SAMPLE_RATE_HZ,
    SAMPLES_PER_FRAME,
    SILENCE_FRAME,
    ASRErrorEvent,
    ASREvent,
    ASRHealth,
    ASRSession,
    ASRSessionConfig,
    AudioChunk,
    EndOfTurnEvent,
    StreamingRecognizer,
    WordEvent,
)

__all__ = [
    "BYTES_PER_SAMPLE",
    "FRAME_DURATION_MS",
    "FRAME_PAYLOAD_BYTES",
    "SAMPLES_PER_FRAME",
    "SAMPLE_RATE_HZ",
    "SILENCE_FRAME",
    "ASRErrorEvent",
    "ASREvent",
    "ASRHealth",
    "ASRSession",
    "ASRSessionConfig",
    "AudioChunk",
    "EndOfTurnEvent",
    "StreamingRecognizer",
    "WordEvent",
]
