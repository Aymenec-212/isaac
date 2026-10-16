"""Real PostgreSQL M1 rehearsal, isolated in a transaction that always rolls back.

No metadata.create_all shortcut: apply the actual 0001..0006 migration functions.
This is not Auth0/browser or concurrent-lock evidence.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from mosaique.domain.ids import new_id
from mosaique.persistence.models import Account, Base
from mosaique.workspaces.service import Workspaces

MIGRATIONS = Path(__file__).parents[2] / "src/mosaique/persistence/migrations/versions"


def apply_revision(connection, revision):
    path = next(MIGRATIONS.glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with Operations.context(context):
        module.upgrade()


@pytest.mark.integration
def test_migration_preserves_legacy_and_workspace_persists(settings):
    engine = create_engine(settings.sync_database_url)
    schema = "m1_" + new_id().lower()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                for revision in ("0001", "0002", "0003"):
                    apply_revision(connection, revision)
                # Exercise real transcript provenance/corrections, not just an empty schema.
                connection.execute(
                    text("INSERT INTO organizations(id,name) VALUES ('org','Legacy')")
                )
                connection.execute(
                    text(
                        "INSERT INTO users(id,organization_id,email,display_name) "
                        "VALUES ('user','org','legacy@test','Legacy')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO meetings(id,organization_id,host_user_id,title,state,language,"
                        "source_kind,transcript_schema_version) "
                        "VALUES ('meeting','org','user','Legacy','COMPLETED','fr','direct',1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO participants(id,meeting_id,organization_id,display_name,role) "
                        "VALUES ('participant','meeting','org','Legacy','host')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO transcript_segments(id,meeting_id,organization_id,"
                        "participant_id,"
                        "sequence,start_ms,end_ms,text,words,status,corrected_text,corrected_by) "
                        "VALUES ('segment','meeting','org','participant',1,0,1000,'raw',"
                        "'[{\"word\":\"raw\"}]'::jsonb,'final','corrected','user')"
                    )
                )
                tables = [
                    "organizations",
                    "users",
                    "meetings",
                    "participants",
                    "audio_sessions",
                    "transcript_segments",
                    "meeting_outputs",
                    "jobs",
                ]

                def snapshot():
                    return {
                        table: connection.execute(
                            text(
                                "SELECT (to_jsonb(t) - 'mode' - 'organizer_account_id' "
                                "- 'organizer_revoked_at')::text "
                                f"FROM {table} t ORDER BY id"
                            )
                        )
                        .scalars()
                        .all()
                        for table in tables
                    }

                before = snapshot()
                apply_revision(connection, "0004")
                assert snapshot() == before
                apply_revision(connection, "0005")
                assert snapshot() == before
                # Existing 0005 sessions remain usable, pending logins are cancelled,
                # and an already-reinvited organizer's audit history is respected.
                connection.execute(
                    text(
                        "INSERT INTO accounts(id,issuer,subject,email,email_verified,disabled) "
                        "VALUES ('old-account','https://old.test/','old-sub','old@test',true,false)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO memberships(organization_id,account_id,role) "
                        "VALUES ('org','old-account','member')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO "
                        "meetings(id,organization_id,organizer_account_id,title,state,language,"
                        "source_kind,transcript_schema_version,mode,created_at) "
                        "VALUES "
                        "('old-enterprise','org','old-account','Private','CREATED','fr','direct',1,"
                        "'enterprise',now() - interval '1 day')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO workspace_audit(id,organization_id,actor_id,action,target_id) "
                        "VALUES "
                        "('old-revocation','org','old-account','membership.revoked','old-account')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO "
                        "login_attempts(state_hash,browser_hash,nonce,verifier,expires_at) "
                        "VALUES ('old-state','old-browser','nonce','verifier',now() + "
                        "interval '10 minutes')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO "
                        "account_sessions(token_hash,account_id,csrf_token,"
                        "last_seen_at,expires_at) "
                        "VALUES ('old-token','old-account','csrf',now(),now() + interval "
                        "'12 hours')"
                    )
                )
                # Include the synthetic enterprise meeting in the preservation snapshot.
                before = snapshot()
                apply_revision(connection, "0006")
                assert connection.scalar(
                    text(
                        "SELECT organizer_revoked_at IS NOT NULL FROM meetings WHERE "
                        "id='old-enterprise'"
                    )
                )
                assert connection.scalar(
                    text(
                        "SELECT a.browser_generation <> b.generation FROM login_attempts a "
                        "JOIN browser_logins b USING(browser_hash) WHERE state_hash='old-state'"
                    )
                )
                assert connection.scalar(
                    text(
                        "SELECT revoked_at IS NULL FROM account_sessions WHERE "
                        "token_hash='old-token'"
                    )
                )
                assert snapshot() == before
                from alembic.autogenerate import compare_metadata

                assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    owner = Account(
                        id=new_id(),
                        issuer="https://identity.test/",
                        subject="auth0|owner",
                        email="legacy@test",
                        email_verified=True,
                    )
                    db.add(owner)
                    db.flush()
                    owner_id = owner.id
                    service = Workspaces(db)
                    assert service.list(owner_id) == []  # No email-based legacy claim.
                    org_id = service.create(owner_id, "New workspace").id
                    db.commit()
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    assert Workspaces(db).authorize(owner_id, org_id).role == "owner"
                    assert [org.id for org in Workspaces(db).list(owner_id)] == [org_id]
                assert snapshot()["transcript_segments"] == before["transcript_segments"]
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
