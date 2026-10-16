"""Minimal durable authorization audit; no invitation secrets or profile content."""

from sqlalchemy.orm import Session

from mosaique.domain.ids import new_id
from mosaique.persistence.models.identity import WorkspaceAudit


def record(
    db: Session, org: str, actor: str, action: str, target: str, *, context_id: str | None = None
) -> None:
    db.add(
        WorkspaceAudit(
            id=new_id(),
            organization_id=org,
            actor_id=actor,
            action=action,
            target_id=target,
            context_id=context_id,
        )
    )
