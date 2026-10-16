"""Real PostgreSQL M1 rehearsal, isolated in a transaction that always rolls back.

No metadata.create_all shortcut: apply the actual 0001..0004 migration functions.
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
                            text(f"SELECT to_jsonb(t)::text FROM {table} t ORDER BY id")
                        )
                        .scalars()
                        .all()
                        for table in tables
                    }

                before = snapshot()
                apply_revision(connection, "0004")
                assert snapshot() == before
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
