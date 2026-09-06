"""The single authorization check (tech spec 13.2).

Implemented once so there is exactly one place to audit and one place to test.
"""

from __future__ import annotations

from mosaique.app.auth.tokens import Principal
from mosaique.domain.errors import Forbidden, NotFound
from mosaique.persistence.models import Meeting


def authorize_meeting_access(principal: Principal, meeting: Meeting | None) -> Meeting:
    """Return the meeting when the principal may see it; raise otherwise.

    A meeting belonging to another organization is reported as NOT_FOUND rather
    than FORBIDDEN, so the API does not confirm that an id exists to a caller
    who has no right to know.
    """
    if meeting is None:
        raise NotFound()
    if meeting.organization_id != principal.organization_id:
        raise NotFound()
    if principal.is_host:
        return meeting
    if principal.meeting_id == meeting.id:
        return meeting
    raise Forbidden("Not a participant in this meeting")


def require_host(principal: Principal) -> None:
    """Host-only operations: end, delete."""
    if not principal.is_host:
        raise Forbidden("Host role required")
