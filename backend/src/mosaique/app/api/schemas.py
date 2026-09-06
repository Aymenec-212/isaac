"""Request and response schemas. These are the wire contract (tech spec 6)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(BaseModel):
    """Every failure response uses this shape (tech spec 6)."""

    error: ErrorBody


class ParticipantView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    role: str


class MeetingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    state: str
    language: str
    source_kind: str
    transcript_version: int | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class MeetingDetailView(MeetingView):
    participants: list[ParticipantView] = Field(default_factory=list)


class CreateMeetingRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class CreateMeetingResponse(BaseModel):
    meeting: MeetingView
    host_token: str
    invite_url: str


class MeetingListResponse(BaseModel):
    meetings: list[MeetingView]


class HealthResponse(BaseModel):
    status: str
    version: str
