"""Engine and session factory. Stages never hand-roll SQL (TECHSPEC decision)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_for(db_url: str) -> Engine:
    return create_engine(db_url)


def session_factory_for(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
