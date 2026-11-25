import os
import sys
from pathlib import Path

import pytest

# Test-only settings. These are set before `app` is imported, so python-dotenv
# (which doesn't override existing variables) never uses .env values in tests.
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_USERNAME"] = "alice"
os.environ.pop("K_SERVICE", None)

# Make the project root importable so tests can `import app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Accounts created in each test database. alice is the admin (ADMIN_USERNAME).
TEST_USERS = {"alice": "password123", "bob": "builder456", "carol": "garden789"}


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    """Tests never call the real Anthropic API or Google Cloud Storage."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)


@pytest.fixture
def make_client(tmp_path):
    """Return a function that builds a test client with the test users added."""
    from app import create_app
    from auth import create_user

    def make(**config):
        app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test",
            "ADMIN_USERNAME": "alice",
            "DATABASE": str(tmp_path / "test.db"),
            **config,
        })
        with app.app_context():
            for username, password in TEST_USERS.items():
                create_user(username, password)
        return app.test_client()

    return make
