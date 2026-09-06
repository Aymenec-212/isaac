"""The authorization matrix (tech spec 13.2). One check, tested once, properly."""

from __future__ import annotations

import pytest

from mosaique.app.auth.authorize import authorize_meeting_access, require_host
from mosaique.app.auth.tokens import (
    Principal,
    hash_token,
    issue_host_token,
    new_invite_token,
    verify_token,
)
from mosaique.domain.errors import Forbidden, InvalidToken, NotFound

SECRET = "unit-test-secret-at-least-32-characters"


class FakeMeeting:
    def __init__(self, meeting_id: str, organization_id: str) -> None:
        self.id = meeting_id
        self.organization_id = organization_id


def host(org="org-a"):
    return Principal(kind="host", subject_id="user-1", organization_id=org)


def guest(org="org-a", meeting="mtg-1"):
    return Principal(kind="participant", subject_id="p-1", organization_id=org, meeting_id=meeting)


def test_host_may_read_own_org_meeting():
    m = FakeMeeting("mtg-1", "org-a")
    assert authorize_meeting_access(host(), m) is m


def test_cross_tenant_read_fails_closed_as_not_found():
    """A meeting in another tenant must not even be confirmed to exist."""
    with pytest.raises(NotFound):
        authorize_meeting_access(host(org="org-a"), FakeMeeting("mtg-1", "org-b"))


def test_missing_meeting_is_not_found():
    with pytest.raises(NotFound):
        authorize_meeting_access(host(), None)


def test_guest_may_read_own_meeting():
    m = FakeMeeting("mtg-1", "org-a")
    assert authorize_meeting_access(guest(), m) is m


def test_guest_may_not_read_another_meeting_in_same_org():
    with pytest.raises(Forbidden):
        authorize_meeting_access(guest(meeting="mtg-1"), FakeMeeting("mtg-2", "org-a"))


def test_require_host_rejects_guest():
    with pytest.raises(Forbidden):
        require_host(guest())
    require_host(host())


def test_token_roundtrip_preserves_tenant():
    token = issue_host_token(user_id="user-1", organization_id="org-a", secret=SECRET, ttl_hours=1)
    p = verify_token(token, secret=SECRET)
    assert p.organization_id == "org-a"
    assert p.is_host


def test_token_signed_with_another_secret_is_rejected():
    token = issue_host_token(user_id="user-1", organization_id="org-a", secret=SECRET, ttl_hours=1)
    with pytest.raises(InvalidToken):
        verify_token(token, secret="a-different-secret-of-sufficient-length")


def test_expired_token_is_rejected():
    token = issue_host_token(user_id="user-1", organization_id="org-a", secret=SECRET, ttl_hours=-1)
    with pytest.raises(InvalidToken):
        verify_token(token, secret=SECRET)


def test_invite_token_is_stored_hashed_not_plain():
    raw = new_invite_token()
    assert hash_token(raw) != raw
    assert len(hash_token(raw)) == 64
