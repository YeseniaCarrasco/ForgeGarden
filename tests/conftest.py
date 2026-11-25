import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parent.parent

# Load .env the same way the app does (existing variables win), so the test
# database URL can be checked against the real one. Nothing from it is printed.
load_dotenv(ROOT / ".env")


def _database_identity(url):
    """(host, port, database) for a connection URL. Neon's pooled host
    ("ep-x-pooler.…") and direct host ("ep-x.…") reach the same database."""
    info = conninfo_to_dict(url)
    host = (info.get("host") or "").lower()
    first, _, rest = host.partition(".")
    first = first.removesuffix("-pooler")
    return (f"{first}.{rest}" if rest else first, str(info.get("port") or 5432), info.get("dbname"))


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
_REAL_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not TEST_DATABASE_URL:
    pytest.exit(
        "TEST_DATABASE_URL is not set. Add a separate test database URL to .env "
        "(or the environment). Tests never use DATABASE_URL.", returncode=2,
    )
if _REAL_DATABASE_URL and (
    TEST_DATABASE_URL == _REAL_DATABASE_URL
    or _database_identity(TEST_DATABASE_URL) == _database_identity(_REAL_DATABASE_URL)
):
    pytest.exit(
        "TEST_DATABASE_URL points at the same database as DATABASE_URL. Refusing to "
        "run, because tests delete every row. Use a separate test database.", returncode=2,
    )

# Test-only settings, set before `app` is imported. The app only ever sees the
# test database: DATABASE_URL is replaced with TEST_DATABASE_URL for the test run.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_USERNAME"] = "alice"
os.environ.pop("K_SERVICE", None)

# Make the project root importable so tests can `import app`.
sys.path.insert(0, str(ROOT))

# Accounts created in each test database. alice is the admin (ADMIN_USERNAME).
TEST_USERS = {"alice": "password123", "bob": "builder456", "carol": "garden789"}


@pytest.fixture(autouse=True)
def empty_test_database():
    """Every test starts with empty tables (ids restart at 1)."""
    from db import empty_tables
    empty_tables(TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    """Tests never call the real Vertex AI or Google Cloud Storage."""
    monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)


@pytest.fixture
def make_client():
    """Return a function that builds a test client with the test users added."""
    from app import create_app
    from auth import create_user

    def make(**config):
        app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test",
            "ADMIN_USERNAME": "alice",
            "DATABASE_URL": TEST_DATABASE_URL,
            **config,
        })
        with app.app_context():
            for username, password in TEST_USERS.items():
                create_user(username, password)
        return app.test_client()

    return make
