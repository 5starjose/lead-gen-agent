"""Alembic-style migration 001 (initial schema).
The app also runs Base.metadata.create_all on startup for first boot; this script is the
versioned migration record for production (run with DATABASE_URL set):
    python migrations/001_initial.py
For real Alembic use: `alembic upgrade head` once alembic.ini is generated from this schema —
tables/constraints/indexes are declared in app/models.py and are the source of truth."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import Base, engine
from app import models  # noqa

revision = "001_initial"
down_revision = None

def upgrade():
    Base.metadata.create_all(bind=engine)
    print("001_initial: all tables created")

if __name__ == "__main__":
    upgrade()
