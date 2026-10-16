import atexit, os, shutil, sys, tempfile, time
# Test isolation: a brand-new temp SQLite file for every pytest session.
# The previous setup pointed DATABASE_URL at ./test_leadgen.db in the repo
# root, so state (and stale -journal files / pooled connections to that file)
# leaked between runs and between tests, producing flaky
# sqlalchemy OperationalErrors ("database is locked" / "table already exists")
# when the fresh_db fixture dropped/recreated tables while another pooled
# connection still held the shared file.
_TEST_DIR = tempfile.mkdtemp(prefix="leadgen-test-")
atexit.register(shutil.rmtree, _TEST_DIR, ignore_errors=True)
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TEST_DIR, "test_leadgen.db")
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["ALLOW_SYNTHETIC_PROVIDER"] = "1"
os.environ["DISABLE_SCHEDULER"] = "1"  # app must not start APScheduler under tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from sqlalchemy.exc import OperationalError
from app.db import Base, engine, SessionLocal
from app import models  # noqa

def _reset_db():
    # Dispose the pool first so no connection from a previous test (or from a
    # TestClient worker thread) still holds the SQLite file while we
    # drop/recreate, and retry briefly if SQLite still reports a lock.
    for attempt in range(5):
        try:
            engine.dispose()
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))

@pytest.fixture(autouse=True)
def fresh_db():
    _reset_db()
    yield
    engine.dispose()

@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()

AUTH = {"Authorization": "Basic YWRtaW46dGVzdC1wYXNzd29yZA=="}  # admin:test-password
