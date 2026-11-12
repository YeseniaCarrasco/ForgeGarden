import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "test",
        "ADMIN_USERNAME": "alice",
        "SITE_NAME": "Test Garden",
    })
    return app.test_client()


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


def test_logout_returns_to_homepage(client):
    login(client, "alice", "password123")
    resp = client.get("/logout")
    assert resp.headers["Location"].endswith("/")


def test_site_name_from_config(client):
    assert b"Test Garden" in client.get("/login").data


def test_non_admin_has_no_badge(client):
    login(client, "bob", "builder456")
    page = client.get("/dashboard")
    assert b"(user)" in page.data
    assert b"Admin access" not in page.data


def login(client, username, password, next_url=None):
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={"username": username, "password": password})


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Log in" in resp.data


def test_valid_login_redirects_to_dashboard(client):
    resp = login(client, "alice", "password123")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    page = client.get("/dashboard")
    assert b"Alice Anvil" in page.data
    assert b"Admin access" in page.data


def test_username_is_case_insensitive(client):
    assert login(client, "BOB", "builder456").status_code == 302


def test_invalid_password_rejected(client):
    resp = login(client, "alice", "wrong")
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_unknown_user_rejected(client):
    resp = login(client, "mallory", "password123")
    assert b"Invalid username or password" in resp.data


def test_dashboard_requires_login(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_next_param_redirects_after_login(client):
    resp = login(client, "bob", "builder456", next_url="/dashboard")
    assert resp.headers["Location"].endswith("/dashboard")


def test_next_redirect_is_local_only(client):
    resp = login(client, "alice", "password123", next_url="//evil.com")
    assert resp.headers["Location"].endswith("/dashboard")


def test_logout_clears_session(client):
    login(client, "carol", "garden789")
    client.get("/logout")
    assert client.get("/dashboard").status_code == 302
