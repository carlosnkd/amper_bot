from typing import Iterator
from sqlalchemy.orm import Session
from yt_backend.db import SessionLocal, engine


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from backend import models

    models.Base.metadata.create_all(bind=engine)
