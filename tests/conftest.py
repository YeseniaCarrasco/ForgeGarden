import os
import sys
from pathlib import Path

import pytest

# Make the project root importable so tests can `import app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    """Tests never call the real Vertex AI or Google Cloud Storage."""
    monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)
