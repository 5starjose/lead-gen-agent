from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import get_settings

settings = get_settings()
# timeout=30 sets SQLite's busy timeout: a writer waits for a lock instead of
# failing immediately with "database is locked" when the scheduler/worker and
# a request touch the file at the same moment.
connect_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def init_db():
    from . import models  # noqa
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
