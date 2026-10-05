"""
db.py
-----
WHAT IT DOES:
    Creates the SQLAlchemy database engine and session factory.
    `get_db()` is a FastAPI dependency: every API request gets its own DB session
    which is closed automatically when the request finishes.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
engine = create_engine(settings.db_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """All ORM tables inherit from this class (see models.py)."""
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
