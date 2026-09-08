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
    ReadinessState,
    RecognizerReadiness,
    StreamingRecognizer,
    WordEvent,
)
from mosaique.speech.interfaces.identity import (
    ASR_VERSION_MAX_LENGTH,
    FAKE_IDENTITY,
    AsrIdentity,
)

__all__ = [
    "ASR_VERSION_MAX_LENGTH",
    "BYTES_PER_SAMPLE",
    "FRAME_DURATION_MS",
    "FRAME_PAYLOAD_BYTES",
    "SAMPLES_PER_FRAME",
    "SAMPLE_RATE_HZ",
    "SILENCE_FRAME",
    "FAKE_IDENTITY",
    "ASRErrorEvent",
    "ASREvent",
    "ASRHealth",
    "ASRSession",
    "ASRSessionConfig",
    "AsrIdentity",
    "AudioChunk",
    "EndOfTurnEvent",
    "ReadinessState",
    "RecognizerReadiness",
    "StreamingRecognizer",
    "WordEvent",
]
