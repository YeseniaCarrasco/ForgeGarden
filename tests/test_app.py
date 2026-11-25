import re
from pathlib import Path

import pytest

from app import create_app
from db import get_db


@pytest.fixture
def client(make_client):
    return make_client(SITE_NAME="Test Garden")


def login(client, username, password, next_url=None):
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={"username": username, "password": password})


def register(client, username, password="longenough1", confirm=None, next_url=None):
    url = "/register" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={
        "username": username, "password": password,
        "confirm": password if confirm is None else confirm,
    })


# ---- public pages ----

def test_homepage_is_about_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Program Goals" in resp.data
    assert b"What is the Forge?" in resp.data
    assert b"CCOF" in resp.data


def test_homepage_has_login_button_when_logged_out(client):
    assert b'href="/login"' in client.get("/").data


def test_homepage_shows_dashboard_button_when_logged_in(client):
    login(client, "alice", "password123")
    assert b'href="/dashboard"' in client.get("/").data


def test_about_url_redirects_to_homepage(client):
    resp = client.get("/about")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_site_name_from_config(client):
    assert b"Test Garden" in client.get("/login").data


@pytest.mark.parametrize("path", ["/", "/about", "/login", "/register", "/static/style.css"])
def test_public_pages_need_no_login(client, path):
    resp = client.get(path)
    assert resp.status_code in (200, 302)
    assert "/login" not in resp.headers.get("Location", "")


@pytest.mark.parametrize("path", [
    "/dashboard", "/calendar", "/calendar?week=2026-12-01", "/calendar/compost/2026-11-20",
    "/plant-help/", "/plant-help/1", "/plant-help/ask",
    "/journal/", "/journal/1", "/journal/new",
])
def test_every_other_page_requires_login(client, path):
    resp = client.get(path)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login?next=")
    assert path.split("?")[0] in resp.headers["Location"].replace("%2F", "/")


def test_post_routes_require_login(client):
    for path in ["/plant-help/1/answer", "/journal/1/delete", "/calendar/compost/2026-11-20"]:
        assert "/login" in client.post(path).headers["Location"]


def test_unknown_url_is_404(client):
    assert client.get("/no-such-page").status_code == 404


# ---- login ----

def test_login_page_renders_without_sample_accounts(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Log in" in resp.data
    assert b"Sample accounts" not in resp.data
    assert b"password123" not in resp.data
    assert b'href="/register' in resp.data


def test_valid_login_redirects_to_dashboard(client):
    resp = login(client, "alice", "password123")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    page = client.get("/dashboard")
    assert b"Hello, alice" in page.data
    assert b"Admin access" in page.data


def test_non_admin_has_no_badge(client):
    login(client, "bob", "builder456")
    page = client.get("/dashboard")
    assert b"Hello, bob" in page.data
    assert b"(user)" in page.data
    assert b"Admin access" not in page.data


def test_username_is_case_insensitive(client):
    assert login(client, "BOB", "builder456").status_code == 302


def test_invalid_password_rejected(client):
    resp = login(client, "alice", "wrong")
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_unknown_user_rejected(client):
    resp = login(client, "mallory", "password123")
    assert b"Invalid username or password" in resp.data


def test_next_param_redirects_after_login(client):
    resp = login(client, "bob", "builder456", next_url="/plant-help/")
    assert resp.headers["Location"].endswith("/plant-help/")


def test_next_redirect_is_local_only(client):
    resp = login(client, "alice", "password123", next_url="//evil.com")
    assert resp.headers["Location"].endswith("/dashboard")


def test_session_for_missing_account_is_cleared(client):
    login(client, "bob", "builder456")
    with client.application.app_context():
        get_db().execute("DELETE FROM users WHERE username = 'bob'")
        get_db().commit()
    assert "/login" in client.get("/dashboard").headers["Location"]


# ---- registration ----

def test_register_creates_account_and_logs_in(client):
    resp = register(client, "Dana_G")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    page = client.get("/dashboard").data
    assert b"Hello, dana_g" in page and b"(user)" in page
    client.post("/logout")
    assert login(client, "dana_g", "longenough1").status_code == 302


def test_register_stores_only_a_hash(client):
    register(client, "dana", password="secret-pass-1")
    with client.application.app_context():
        row = get_db().execute("SELECT * FROM users WHERE username = 'dana'").fetchone()
    assert row["password_hash"] != "secret-pass-1"
    assert "secret-pass-1" not in row["password_hash"]
    assert row["password_hash"].startswith(("scrypt:", "pbkdf2:"))
    assert row["created_at"]


def test_register_honors_next(client):
    resp = register(client, "dana", next_url="/plant-help/ask")
    assert resp.headers["Location"].endswith("/plant-help/ask")


@pytest.mark.parametrize("username, ok", [
    ("ab", False), ("abc", True), ("a" * 32, True), ("a" * 33, False),
    ("has space", False), ("<b>", False),
])
def test_username_rules(client, username, ok):
    assert (register(client, username).status_code == 302) is ok


def test_password_rules(client):
    resp = register(client, "dana", password="short7!")
    assert resp.status_code == 400
    assert b"at least 8 characters" in resp.data
    assert register(client, "dana", password="exactly8").status_code == 302


def test_passwords_must_match(client):
    resp = register(client, "dana", password="longenough1", confirm="longenough2")
    assert resp.status_code == 400
    assert b"don&#39;t match" in resp.data


def test_duplicate_username_rejected(client):
    resp = register(client, "BOB")
    assert resp.status_code == 400
    assert b"username is taken" in resp.data
    assert login(client, "bob", "builder456").status_code == 302  # unchanged


def test_admin_is_whoever_has_admin_username(make_client):
    client = make_client(ADMIN_USERNAME="Dana")
    register(client, "dana")
    assert b"Admin access" in client.get("/dashboard").data
    client.post("/logout")
    login(client, "alice", "password123")
    assert b"Admin access" not in client.get("/dashboard").data


# ---- logout ----

def test_logout_is_post_only(client):
    login(client, "alice", "password123")
    assert client.get("/logout").status_code == 405
    assert client.get("/dashboard").status_code == 200  # still logged in


def test_logout_returns_to_homepage(client):
    login(client, "alice", "password123")
    resp = client.post("/logout")
    assert resp.headers["Location"].endswith("/")


def test_logout_clears_session(client):
    login(client, "carol", "garden789")
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302


def test_dashboard_logout_is_a_form_button(client):
    login(client, "carol", "garden789")
    page = client.get("/dashboard").get_data(as_text=True)
    assert '<form method="post" action="/logout">' in page
    assert 'href="/logout"' not in page


# ---- settings ----

@pytest.mark.parametrize("name", ["SECRET_KEY", "ADMIN_USERNAME"])
def test_missing_setting_stops_startup(monkeypatch, name):
    monkeypatch.setenv(name, "")
    with pytest.raises(RuntimeError, match=name):
        create_app()


def test_settings_come_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "from-env")
    monkeypatch.setenv("ADMIN_USERNAME", " Dana ")
    app = create_app({"DATABASE": str(tmp_path / "t.db")})
    assert app.config["SECRET_KEY"] == "from-env"
    assert app.config["ADMIN_USERNAME"] == "dana"


def test_no_fallback_secret_in_code():
    source = (Path(__file__).resolve().parent.parent / "app.py").read_text()
    assert "dev-only" not in source
    assert "debug=True" not in source


# ---- session cookie ----

def session_cookie_header(client):
    resp = login(client, "alice", "password123")
    return next(h for h in resp.headers.getlist("Set-Cookie") if h.startswith("session="))


def test_session_cookie_flags_locally(client):
    header = session_cookie_header(client)
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Secure" not in header


def test_session_cookie_secure_on_cloud_run(monkeypatch, make_client):
    monkeypatch.setenv("K_SERVICE", "forgegarden")
    header = session_cookie_header(make_client())
    assert "Secure" in header and "HttpOnly" in header and "SameSite=Lax" in header


# ---- CSRF ----

def test_csrf_blocks_posts_without_token(make_client):
    client = make_client(WTF_CSRF_ENABLED=True)
    assert login(client, "alice", "password123").status_code == 400
    assert register(client, "dana").status_code == 400


def test_csrf_allows_posts_with_token(make_client):
    client = make_client(WTF_CSRF_ENABLED=True)
    page = client.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    resp = client.post("/login", data={
        "username": "alice", "password": "password123", "csrf_token": token,
    })
    assert resp.status_code == 302
    assert client.post("/logout").status_code == 400  # token missing
    # Logging in starts a fresh session, so the pre-login token no longer works.
    assert client.post("/logout", data={"csrf_token": token}).status_code == 400
    page = client.get("/dashboard").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302


def test_every_post_form_has_csrf_field():
    templates = Path(__file__).resolve().parent.parent / "templates"
    forms = 0
    for path in templates.glob("*.html"):
        for form in re.findall(r"<form\b.*?</form>", path.read_text(encoding="utf-8"), re.S | re.I):
            if re.search(r'method="post"', form, re.I):
                forms += 1
                assert 'name="csrf_token" value="{{ csrf_token() }}"' in form, path.name
    assert forms >= 12
