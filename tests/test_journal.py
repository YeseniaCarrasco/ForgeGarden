import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "ADMIN_USERNAME": "alice",
        "DATABASE": str(tmp_path / "test.db"),
    })
    return app.test_client()


def login(client, username="alice", password="password123"):
    client.get("/logout")
    client.post("/login", data={"username": username, "password": password})


POST = {
    "kind": "reading",
    "title": "On soil as a living system",
    "body": "First paragraph about soil life.\n\nSecond paragraph.",
    "link_title": "A book about soil",
    "link_url": "https://example.org/soil",
}


def publish(client, **overrides):
    return client.post("/journal/new", data={**POST, **overrides})


def test_journal_is_public_with_empty_state(client):
    page = client.get("/journal/").get_data(as_text=True)
    assert "Garden Journal" in page
    assert "No journal posts yet" in page
    assert "New post" not in page


def test_admin_publishes_and_anyone_can_read(client):
    login(client)
    resp = publish(client)
    assert resp.headers["Location"].endswith("/journal/1")
    client.get("/logout")
    listing = client.get("/journal/").get_data(as_text=True)
    assert "On soil as a living system" in listing
    assert "First paragraph about soil life." in listing
    assert "Second paragraph." not in listing  # only the excerpt
    page = client.get("/journal/1").get_data(as_text=True)
    assert "Second paragraph." in page
    assert 'href="https://example.org/soil"' in page
    assert "A book about soil" in page
    assert "Garden Manager" in page
    assert "Edit" not in page


def test_kind_filter(client):
    login(client)
    publish(client)
    publish(client, kind="thought", title="Why we leave the clover")
    page = client.get("/journal/?kind=thought").get_data(as_text=True)
    assert "Why we leave the clover" in page and "On soil" not in page


def test_non_admins_cannot_write(client):
    assert "/login" in client.get("/journal/new").headers["Location"]
    login(client, "bob", "builder456")
    assert client.get("/journal/new").status_code == 403
    assert publish(client).status_code == 403
    assert "New post" not in client.get("/journal/").get_data(as_text=True)


def test_non_admins_cannot_edit_or_delete(client):
    login(client)
    publish(client)
    login(client, "bob", "builder456")
    assert client.post("/journal/1/edit", data=POST).status_code == 403
    assert client.post("/journal/1/delete").status_code == 403


def test_validation(client):
    login(client)
    resp = publish(client, title="", kind="rant")
    assert resp.status_code == 400
    page = resp.get_data(as_text=True)
    assert "Title is required" in page and "choose a post type" in page


def test_only_http_links_allowed(client):
    login(client)
    assert publish(client, link_url="javascript:alert(1)").status_code == 400
    assert publish(client, link_url="").status_code == 302  # link is optional


def test_edit_and_delete(client):
    login(client)
    publish(client)
    resp = client.post("/journal/1/edit", data={**POST, "title": "Soil, revisited"})
    assert resp.status_code == 302
    page = client.get("/journal/1").get_data(as_text=True)
    assert "Soil, revisited" in page and "edited" in page
    assert client.post("/journal/1/delete").status_code == 302
    assert client.get("/journal/1").status_code == 404


def test_header_links(client):
    page = client.get("/").get_data(as_text=True)
    assert 'href="/plant-help/"' in page and 'href="/journal/"' in page
