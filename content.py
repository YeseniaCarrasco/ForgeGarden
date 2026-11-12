"""Helpers for user-written text on the Plant Help board and Garden Journal.

Posts are stored and shown as plain text (Jinja escapes any HTML), so
formatting is limited to paragraphs separated by blank lines.
"""
import re
from datetime import datetime, timezone

_BLANK_LINES = re.compile(r"\n\s*\n")


def paragraphs(text):
    """Split text into paragraphs on blank lines."""
    text = (text or "").replace("\r\n", "\n").strip()
    return [p.strip() for p in _BLANK_LINES.split(text) if p.strip()]


def excerpt(text, limit=240):
    """First paragraph, shortened to about `limit` characters."""
    first = (paragraphs(text) or [""])[0]
    if len(first) <= limit:
        return first
    return first[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def short_date(timestamp):
    """SQLite CURRENT_TIMESTAMP (UTC) -> 'Nov 11, 2026' in the server's local time."""
    when = datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc).astimezone()
    return f"{when:%b} {when.day}, {when.year}"


def clean(form, field, label, max_len, required=True):
    """Read a trimmed form field. Returns (value, error message or None)."""
    value = (form.get(field) or "").strip()
    if required and not value:
        return value, f"{label} is required."
    if len(value) > max_len:
        return value, f"{label} must be {max_len} characters or fewer."
    return value, None


def clean_url(form, field, label):
    """Optional http(s) link. Other schemes (like javascript:) are rejected."""
    value = (form.get(field) or "").strip()
    if value and not re.match(r"https?://[^\s]+$", value, re.IGNORECASE):
        return value, f"{label} must be a full web address starting with http:// or https://."
    if len(value) > 500:
        return value, f"{label} must be 500 characters or fewer."
    return value, None
