"""Public error taxonomy (tech spec 13.4).

Internal exceptions are mapped to these stable codes at the API boundary.
Vendor exceptions and stack traces never reach a client.
"""

from __future__ import annotations

from enum import StrEnum
from http import HTTPStatus


class ErrorCode(StrEnum):
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    MEETING_NOT_FOUND = "MEETING_NOT_FOUND"
    MEETING_NOT_LIVE = "MEETING_NOT_LIVE"
    MEETING_INVALID_TRANSITION = "MEETING_INVALID_TRANSITION"
    AUDIO_INVALID_FRAME = "AUDIO_INVALID_FRAME"
    AUDIO_QUEUE_OVERLOADED = "AUDIO_QUEUE_OVERLOADED"
    SESSION_REPLACED = "SESSION_REPLACED"
    TRANSPORT_STALLED = "TRANSPORT_STALLED"
    ASR_UNAVAILABLE = "ASR_UNAVAILABLE"
    ASR_TIMEOUT = "ASR_TIMEOUT"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    POSTPROCESSING_FAILED = "POSTPROCESSING_FAILED"
    # Slice 6R item 7. A correction that changes nothing, or names a speaker who
    # was never in the room, is a client mistake rather than a state conflict —
    # and reusing AUDIO_INVALID_FRAME for a text edit would make the taxonomy
    # lie. Extends §6's list rather than deviating from it.
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


STATUS_FOR_CODE: dict[ErrorCode, int] = {
    ErrorCode.AUTH_INVALID_TOKEN: HTTPStatus.UNAUTHORIZED,
    ErrorCode.AUTH_FORBIDDEN: HTTPStatus.FORBIDDEN,
    ErrorCode.MEETING_NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.MEETING_NOT_LIVE: HTTPStatus.CONFLICT,
    ErrorCode.MEETING_INVALID_TRANSITION: HTTPStatus.CONFLICT,
    ErrorCode.AUDIO_INVALID_FRAME: HTTPStatus.BAD_REQUEST,
    ErrorCode.AUDIO_QUEUE_OVERLOADED: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.SESSION_REPLACED: HTTPStatus.CONFLICT,
    ErrorCode.TRANSPORT_STALLED: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.ASR_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.ASR_TIMEOUT: HTTPStatus.GATEWAY_TIMEOUT,
    ErrorCode.PERSISTENCE_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.POSTPROCESSING_FAILED: HTTPStatus.INTERNAL_SERVER_ERROR,
    ErrorCode.VALIDATION_FAILED: HTTPStatus.BAD_REQUEST,
    ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
}


class MosaiqueError(Exception):
    """Base for errors that carry a public code and a safe message."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status_code(self) -> int:
        return STATUS_FOR_CODE[self.code]


class NotFound(MosaiqueError):
    def __init__(self, message: str = "Meeting not found") -> None:
        super().__init__(ErrorCode.MEETING_NOT_FOUND, message)


class Forbidden(MosaiqueError):
    def __init__(self, message: str = "Not permitted") -> None:
        super().__init__(ErrorCode.AUTH_FORBIDDEN, message)


class InvalidToken(MosaiqueError):
    def __init__(self, message: str = "Invalid or expired token") -> None:
        super().__init__(ErrorCode.AUTH_INVALID_TOKEN, message)
