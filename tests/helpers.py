"""Shared helpers for the photo, Plant Doctor, and farmstand tests."""
import io
from datetime import date

from app import create_app

TODAY = date(2026, 11, 18)  # a Wednesday; the next farmstand is Friday, Nov 20
NEXT_FRIDAY = "2026-11-20"

# Just enough bytes to look like each image type.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def make_app(tmp_path, **config):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "ADMIN_USERNAME": "alice",
        "DATABASE": str(tmp_path / "test.db"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "TODAY": TODAY,
        **config,
    })


def photo(data=PNG, name="leaf.png"):
    return (io.BytesIO(data), name)


def login(client, username):
    passwords = {"alice": "password123", "bob": "builder456", "carol": "garden789"}
    client.get("/logout")
    client.post("/login", data={"username": username, "password": passwords[username]})


def uploaded_files(tmp_path):
    folder = tmp_path / "uploads"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []
