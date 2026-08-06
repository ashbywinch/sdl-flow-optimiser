"""Declarative base and shared column types."""

from __future__ import annotations

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# jsonb on Postgres, plain JSON on SQLite so unit tests need no server.
# jsonb is searchable (containment, GIN); the "binary" storage is an
# implementation detail, not an opaque blob (TECHSPEC decision).
JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")
