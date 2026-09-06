"""SQLAlchemy declarative base and shared column helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column

# Explicit naming so Alembic autogenerate produces stable constraint names.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def ulid_pk() -> MappedColumn[str]:
    """26-character ULID primary key."""
    return mapped_column(String(26), primary_key=True)


def created_at_col() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_col() -> MappedColumn[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# JSONB payloads are heterogeneous (lists for key_points, objects for words),
# so they are typed as Any rather than pretending to be dict.
Json = Any

__all__ = ["Base", "Json", "created_at_col", "ulid_pk", "updated_at_col"]
