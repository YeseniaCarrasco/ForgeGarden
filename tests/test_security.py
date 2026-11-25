"""Tests for the fixes from the AI-assisted security review (see SECURITY_REVIEW.md)."""
import json
from types import SimpleNamespace

import pytest

import auth
import plant_doctor
from content import local_path
from helpers import NEXT_FRIDAY, login, make_app

GOOD_DIAGNOSIS = {
    "topic": "pests",
    "likely_issues": ["Aphids under the leaves."],
    "organic_treatment": "Spray them off with water.",
}


class FakeMessages:
    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=self.reply)])


def use_fake(app, reply):
    fake = FakeMessages(reply)
    app.extensions["anthropic_client"] = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    return fake


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


# ---- Open redirects ----

@pytest.mark.parametrize("url", ["/dashboard", "/farmstand/?day=2026-11-20", "/plant-help/1#answers"])
def test_local_paths_are_allowed(url):
    assert local_path(url) == url


@pytest.mark.parametrize("url", [
    "", "dashboard", "https://evil.example", "//evil.example", "/\\evil.example",
    "/\t/evil.example", "/\n/evil.example", "/ /evil.example", "/\x00evil",
])
def test_other_sites_are_rejected(url):
    assert local_path(url) is None


def test_login_does_not_redirect_off_site(app):
    client = app.test_client()
    r = client.post("/login?next=/%09/evil.example",
                    data={"username": "bob", "password": "builder456"})
    assert r.status_code == 302
    assert "evil.example" not in r.headers["Location"]
    assert r.headers["Location"].endswith("/dashboard")


def test_login_still_follows_local_next(app):
    client = app.test_client()
    r = client.post("/login?next=/farmstand/",
                    data={"username": "bob", "password": "builder456"})
    assert r.headers["Location"].endswith("/farmstand/")


def test_farmstand_cancel_does_not_redirect_off_site(app):
    client = app.test_client()
    login(client, "bob")
    r = client.post(f"/farmstand/{NEXT_FRIDAY}/cancel", data={"next": "/\t/evil.example"})
    assert "evil.example" not in r.headers["Location"]


# ---- Password guessing ----

def test_login_locks_after_too_many_failures(app, monkeypatch):
    monkeypatch.setattr(auth, "MAX_FAILED_LOGINS", 3)
    client = app.test_client()
    for _ in range(3):
        client.post("/login", data={"username": "bob", "password": "wrong-password"})

    r = client.post("/login", data={"username": "bob", "password": "builder456"})
    assert r.status_code == 429
    assert "Too many failed login attempts" in r.get_data(as_text=True)
    assert client.get("/dashboard").status_code == 302  # still not logged in

    # Other accounts are unaffected.
    login(client, "carol")
    assert client.get("/dashboard").status_code == 200


def test_successful_login_clears_failures(app, monkeypatch):
    monkeypatch.setattr(auth, "MAX_FAILED_LOGINS", 3)
    client = app.test_client()
    for _ in range(2):
        client.post("/login", data={"username": "bob", "password": "wrong-password"})
    login(client, "bob")
    client.post("/logout")
    for _ in range(2):
        client.post("/login", data={"username": "bob", "password": "wrong-password"})
    # Only 2 failures since the last success, so bob can still log in.
    login(client, "bob")
    assert client.get("/dashboard").status_code == 200


# ---- Security headers ----

def test_security_headers_on_every_page(app):
    r = app.test_client().get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Strict-Transport-Security" not in r.headers  # plain HTTP locally


def test_hsts_when_served_over_https(tmp_path):
    app = make_app(tmp_path, SESSION_COOKIE_SECURE=True)
    assert "max-age=" in app.test_client().get("/").headers["Strict-Transport-Security"]


# ---- AI spending limits ----

def ask(client, n):
    return client.post("/plant-help/ask", data={"topic": "pests", "title": f"Question {n}",
                                                "body": "Bugs on my kale."},
                       follow_redirects=True).get_data(as_text=True)


def test_plant_doctor_per_user_daily_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(plant_doctor, "PLANT_DOCTOR_DAILY_LIMIT", 2)
    app = make_app(tmp_path, ANTHROPIC_API_KEY="test-key")
    fake = use_fake(app, json.dumps(GOOD_DIAGNOSIS))
    client = app.test_client()
    login(client, "bob")
    ask(client, 1)
    ask(client, 2)
    page = ask(client, 3)
    assert "reached its daily limit" in page
    assert "Question 3" in page  # the question is still posted
    assert len(fake.requests) == 2

    # The limit is per person.
    login(client, "carol")
    ask(client, 4)
    assert len(fake.requests) == 3


def test_site_wide_daily_limit_covers_chat(tmp_path, monkeypatch):
    monkeypatch.setattr(plant_doctor, "SITE_DAILY_LIMIT", 1)
    app = make_app(tmp_path, ANTHROPIC_API_KEY="test-key")
    fake = use_fake(app, "Hello from the garden!")
    client = app.test_client()
    login(client, "bob")
    client.post("/garden-helper/", data={"message": "first"})
    login(client, "carol")
    page = client.post("/garden-helper/", data={"message": "second"},
                       follow_redirects=True).get_data(as_text=True)
    assert "daily limit for the whole site" in page
    assert len(fake.requests) == 1
