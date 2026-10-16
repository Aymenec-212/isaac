"""AUTH-02..04 local domain evidence; SQLite cannot prove PG locking or Auth0."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mosaique.domain.errors import Forbidden, InvalidToken, MosaiqueError, NotFound
from mosaique.domain.ids import new_id
from mosaique.persistence.models import Account, Invitation, Membership, Organization
from mosaique.workspaces.service import Workspaces


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'workspaces.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    from mosaique.persistence.models import Meeting
    from mosaique.persistence.models.identity import MeetingAccess, WorkspaceAudit

    for model in (
        Organization,
        Account,
        Membership,
        Invitation,
        Meeting,
        MeetingAccess,
        WorkspaceAudit,
    ):
        model.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def account(db, email="owner@example.test", *, subject=None):
    row = Account(
        id=new_id(),
        issuer="https://identity.example.test/",
        subject=subject or new_id(),
        email=email,
        email_verified=True,
    )
    db.add(row)
    db.flush()
    return row


def test_create_switch_reload_without_email_merge(db):
    owner, separate = account(db), account(db)
    service = Workspaces(db)
    a, b = service.create(owner.id, "Alpha"), service.create(owner.id, "Beta")
    service.rename(owner.id, a.id, "Renamed")
    owner_id, a_id, b_id, separate_id = owner.id, a.id, b.id, separate.id
    db.commit()
    with Session(db.get_bind()) as restarted:
        service = Workspaces(restarted)
        assert {org.id for org in service.list(owner_id)} == {a_id, b_id}
        assert service.authorize(owner_id, a_id).role == "owner"
        assert restarted.get(Organization, a_id).name == "Renamed"
        assert service.list(separate_id) == []
        with pytest.raises(NotFound):
            service.authorize(separate_id, a_id)


def test_invite_replay_verified_address_and_hash(db):
    owner, member, stranger = account(db), account(db, "member@test"), account(db, "x@test")
    service = Workspaces(db)
    org = service.create(owner.id, "Alpha")
    token = service.invite(owner.id, org.id, " MEMBER@test ")
    invitation = db.scalar(select(Invitation))
    assert invitation.token_hash != token
    assert len(invitation.token_hash) == 64
    with pytest.raises(Forbidden):
        service.accept(stranger.id, token)
    member.email_verified = False
    db.flush()
    with pytest.raises(Forbidden):
        service.accept(member.id, token)
    member.email_verified = True
    db.flush()
    assert service.accept(member.id, token).id == org.id
    assert service.authorize(member.id, org.id).role == "member"
    for invalid in (token, "unknown"):
        with pytest.raises(NotFound):
            service.accept(member.id, invalid)


def test_expired_invite_and_disabled_inviter(db):
    owner, member = account(db), account(db, "member@test")
    service = Workspaces(db)
    org = service.create(owner.id, "Alpha")
    token = service.invite(owner.id, org.id, member.email)
    invitation = db.scalar(select(Invitation))
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    with pytest.raises(NotFound):
        service.accept(member.id, token)
    invitation.expires_at = datetime.now(UTC) + timedelta(days=1)
    owner.disabled = True
    db.flush()
    with pytest.raises(InvalidToken):
        service.accept(member.id, token)


def test_member_and_other_tenant_cannot_manage(db):
    owner, member, outsider = account(db), account(db, "member@test"), account(db, "outsider@test")
    service = Workspaces(db)
    org, other = service.create(owner.id, "Alpha"), service.create(outsider.id, "Other")
    service.accept(member.id, service.invite(owner.id, org.id, member.email))
    for action in (
        lambda: service.rename(member.id, org.id, "Hacked"),
        lambda: service.invite(member.id, org.id, outsider.email),
        lambda: service.change_member(member.id, org.id, owner.id, role=None),
    ):
        with pytest.raises(Forbidden):
            action()
    for action in (
        lambda: service.authorize(owner.id, other.id),
        lambda: service.rename(owner.id, other.id, "Hacked"),
        lambda: service.invite(owner.id, other.id, member.email),
        lambda: service.change_member(owner.id, other.id, outsider.id, role=None),
    ):
        with pytest.raises(NotFound):
            action()


def test_revoke_rechecks_cached_membership_and_invalidates_pending_invite(db):
    owner, member = account(db), account(db, "member@test")
    service = Workspaces(db)
    a, b = service.create(owner.id, "Alpha"), service.create(owner.id, "Beta")
    service.accept(member.id, service.invite(owner.id, a.id, member.email))
    service.accept(member.id, service.invite(owner.id, b.id, member.email))
    stale = service.invite(owner.id, a.id, member.email)
    ids = owner.id, member.id, a.id, b.id
    db.commit()
    with Session(db.get_bind()) as cached:
        reader = Workspaces(cached)
        assert reader.authorize(ids[1], ids[2])
        service.change_member(ids[0], ids[2], ids[1], role=None)
        db.commit()
        with pytest.raises(NotFound):
            reader.authorize(ids[1], ids[2])
        assert [o.id for o in reader.list(ids[1])] == [ids[3]]
        with pytest.raises(NotFound):
            reader.accept(ids[1], stale)
    service.accept(ids[1], service.invite(ids[0], ids[2], member.email))
    assert service.authorize(ids[1], ids[2]).role == "member"


def test_last_owner_and_duplicate_invite_do_not_demote(db):
    owner, second = account(db), account(db, "second@test")
    service = Workspaces(db)
    org = service.create(owner.id, "Alpha")
    for role in (None, "member", "admin"):
        with pytest.raises(Forbidden):
            service.change_member(owner.id, org.id, owner.id, role=role)
    service.accept(owner.id, service.invite(owner.id, org.id, owner.email))
    assert service.authorize(owner.id, org.id).role == "owner"
    service.accept(second.id, service.invite(owner.id, org.id, second.email))
    service.change_member(owner.id, org.id, second.id, role="owner")
    service.change_member(owner.id, org.id, owner.id, role=None)
    assert service.authorize(second.id, org.id).role == "owner"
    with pytest.raises(NotFound):
        service.authorize(owner.id, org.id)


def test_bad_input_missing_disabled_account(db):
    owner = account(db)
    service = Workspaces(db)
    for name in (" ", "a" * 201):
        with pytest.raises(MosaiqueError):
            service.create(owner.id, name)
    with pytest.raises(InvalidToken):
        service.create(new_id(), "Alpha")
    org = service.create(owner.id, "Alpha")
    with pytest.raises(MosaiqueError):
        service.invite(owner.id, org.id, "invalid")
    owner.disabled = True
    db.flush()
    for action in (lambda: service.list(owner.id), lambda: service.authorize(owner.id, org.id)):
        with pytest.raises(InvalidToken):
            action()


def test_unique_identity_and_foreign_keys(db):
    original = account(db, subject="auth0|stable")
    db.commit()
    with pytest.raises(IntegrityError):
        account(db, subject="auth0|stable")
    db.rollback()
    db.add(Membership(organization_id=new_id(), account_id=original.id, role="owner"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_rollback_leaves_no_workspace_or_invite(db):
    owner = account(db)
    db.commit()
    service = Workspaces(db)
    org = service.create(owner.id, "Uncommitted")
    service.invite(owner.id, org.id, "member@test")
    db.rollback()
    assert service.list(owner.id) == []
    assert db.scalar(select(Invitation)) is None


def test_revoked_inviter_cannot_revive_old_invites(db):
    owner, admin, guest = account(db), account(db, "admin@test"), account(db, "guest@test")
    service = Workspaces(db)
    org = service.create(owner.id, "Alpha")
    service.accept(admin.id, service.invite(owner.id, org.id, admin.email))
    service.change_member(owner.id, org.id, admin.id, role="admin")
    stale = service.invite(admin.id, org.id, guest.email)
    service.change_member(owner.id, org.id, admin.id, role="member")
    service.change_member(owner.id, org.id, admin.id, role="admin")
    with pytest.raises(NotFound):
        service.accept(guest.id, stale)


def test_owner_can_revoke_disabled_member(db):
    owner, member = account(db), account(db, "member@test")
    service = Workspaces(db)
    org = service.create(owner.id, "Alpha")
    service.accept(member.id, service.invite(owner.id, org.id, member.email))
    member.disabled = True
    db.flush()
    service.change_member(owner.id, org.id, member.id, role=None)
    assert db.get(Membership, (org.id, member.id)).revoked_at is not None


def test_cross_tenant_inviter_constraint(db):
    owner, outsider = account(db), account(db, "outsider@test")
    service = Workspaces(db)
    org = service.create(owner.id, "Alpha")
    service.create(outsider.id, "Other")
    db.add(
        Invitation(
            id=new_id(),
            organization_id=org.id,
            invited_by=outsider.id,
            email="member@test",
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_disabled_coowner_does_not_satisfy_last_active_owner(db):
    owner, second = account(db), account(db, "second@test")
    service = Workspaces(db)
    org = service.create(owner.id, "Alpha")
    service.accept(second.id, service.invite(owner.id, org.id, second.email))
    service.change_member(owner.id, org.id, second.id, role="owner")
    second.disabled = True
    db.flush()
    with pytest.raises(Forbidden):
        service.change_member(owner.id, org.id, owner.id, role=None)
    service.change_member(owner.id, org.id, second.id, role=None)


def test_migration_is_additive_and_matches_new_model_tables():
    """Execute the actual migration on SQLite and compare its schema to the models.

    Does not replace the PostgreSQL rehearsal or locking checks.
    """
    import importlib.util
    from pathlib import Path

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import MetaData

    path = Path(__file__).parents[2] / (
        "src/mosaique/persistence/migrations/versions/0004_workspace_identity.py"
    )
    spec = importlib.util.spec_from_file_location("m1_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            Organization.__table__.create(connection)
            connection.execute(Organization.__table__.insert().values(id="legacy", name="Legacy"))
            metadata = MetaData(naming_convention=Organization.metadata.naming_convention)
            for model in (Organization, Account, Membership, Invitation):
                model.__table__.to_metadata(metadata)
            metadata.tables["accounts"]._columns.remove(metadata.tables["accounts"].c.display_name)
            metadata.tables["accounts"]._columns.remove(metadata.tables["accounts"].c.login_generation)
            context = MigrationContext.configure(connection, opts={"target_metadata": metadata})
            with Operations.context(context):
                module.upgrade()
            assert compare_metadata(context, metadata) == []
            assert connection.execute(select(Organization.name)).scalar_one() == "Legacy"
            with pytest.raises(RuntimeError, match="preserve data"):
                module.downgrade()
    finally:
        engine.dispose()
