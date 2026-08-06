from typing import Iterator
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.db import SessionLocal, engine


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_agent_traces() -> None:
    """
    agent_traces' schema changed from "one row per phase, holding a JSON blob of steps"
    to "one row per step, grouped by turn_id" (see models.py's AgentTraces docstring).
    create_all() below only creates tables that don't exist yet -- it never alters an
    existing one -- so a pre-existing table from before this change would still have the
    old columns and break every insert/select against the new ones. Drop it if it's still
    on the old shape so create_all() recreates it correctly; safe to lose, since this
    table only ever holds derived trace/debug data, never anything user-authored.
    """
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_traces)"))}
        if columns and "turn_id" not in columns:
            conn.execute(text("DROP TABLE agent_traces"))
            conn.commit()


def init_db() -> None:
    from backend import models

    _migrate_agent_traces()
    models.Base.metadata.create_all(bind=engine)
