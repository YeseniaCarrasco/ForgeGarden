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


def login(client, username, password):
    client.get("/logout")
    client.post("/login", data={"username": username, "password": password})


def as_bob(client):
    login(client, "bob", "builder456")


def as_carol(client):
    login(client, "carol", "garden789")


def as_alice(client):  # the admin / garden manager
    login(client, "alice", "password123")


def ask(client, title="Why are my squash leaves wilting?", topic="wilting",
        body="Leaves droop every afternoon.\n\nSoil seems damp."):
    return client.post("/plant-help/ask", data={"topic": topic, "title": title, "body": body})


def answer(client, qid=1, body="Check for squash vine borers at the base of the stem."):
    return client.post(f"/plant-help/{qid}/answer", data={"body": body})


# ---- viewing ----

def test_board_is_public_with_empty_state(client):
    page = client.get("/plant-help/").get_data(as_text=True)
    assert "Plant Help" in page
    assert "No questions yet" in page
    assert "Organic answers only" in page
    assert "Log in to ask" in page


def test_questions_and_answers_visible_when_logged_out(client):
    as_bob(client)
    ask(client)
    answer(client)
    client.get("/logout")
    listing = client.get("/plant-help/").get_data(as_text=True)
    assert "Why are my squash leaves wilting?" in listing
    assert "1 answer" in listing
    page = client.get("/plant-help/1").get_data(as_text=True)
    assert "squash vine borers" in page
    assert "<p>Leaves droop every afternoon.</p>" in page  # paragraphs
    assert "Log in</a> to answer" in page
    assert 'action="/plant-help/1/answer"' not in page


def test_topic_filter(client):
    as_bob(client)
    ask(client, title="Aphids on kale", topic="pests")
    ask(client, title="Droopy basil", topic="wilting")
    page = client.get("/plant-help/?topic=pests").get_data(as_text=True)
    assert "Aphids on kale" in page and "Droopy basil" not in page
    assert "Droopy basil" in client.get("/plant-help/?topic=bogus").get_data(as_text=True)


def test_missing_question_is_404(client):
    assert client.get("/plant-help/99").status_code == 404


def test_html_is_escaped(client):
    as_bob(client)
    ask(client, title="<script>alert(1)</script>")
    page = client.get("/plant-help/1").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# ---- asking and answering ----

def test_asking_requires_login(client):
    assert "/login" in client.get("/plant-help/ask").headers["Location"]
    assert "/login" in ask(client).headers["Location"]


def test_ask_validation(client):
    as_bob(client)
    resp = ask(client, title="", topic="nope")
    assert resp.status_code == 400
    page = resp.get_data(as_text=True)
    assert "Please choose a topic" in page and "Title is required" in page
    assert ask(client, title="x" * 151).status_code == 400


def test_ask_and_answer(client):
    as_bob(client)
    resp = ask(client)
    assert resp.headers["Location"].endswith("/plant-help/1")
    as_carol(client)
    assert answer(client).status_code == 302
    assert "squash vine borers" in client.get("/plant-help/1").get_data(as_text=True)


def test_answer_requires_login_and_text(client):
    as_bob(client)
    ask(client)
    assert answer(client, body="   ").status_code == 400
    client.get("/logout")
    assert "/login" in answer(client).headers["Location"]


def test_answer_to_missing_question_is_404(client):
    as_bob(client)
    assert answer(client, qid=42).status_code == 404


def test_garden_manager_badge(client):
    as_bob(client)
    ask(client)
    as_alice(client)  # admin
    answer(client, body="Mulch helps keep roots cool.")
    as_carol(client)
    answer(client, body="Try watering in the morning.")
    page = client.get("/plant-help/1").get_data(as_text=True)
    assert page.count("Garden Manager</span>") == 1


# ---- marking helpful ----

def test_only_asker_can_mark_helpful(client):
    as_bob(client)
    ask(client)
    as_carol(client)
    answer(client)
    assert client.post("/plant-help/1/helpful/1").status_code == 403
    as_bob(client)
    assert b"This helped" in client.get("/plant-help/1").data
    client.post("/plant-help/1/helpful/1")
    page = client.get("/plant-help/1").get_data(as_text=True)
    assert "This helped Bob Builder" in page
    assert "✓ Helped" in client.get("/plant-help/").get_data(as_text=True)
    client.post("/plant-help/1/helpful/1")  # toggle off
    assert "This helped Bob Builder" not in client.get("/plant-help/1").get_data(as_text=True)


def test_cannot_mark_answer_from_another_question(client):
    as_bob(client)
    ask(client)
    ask(client, title="Second question")
    answer(client, qid=2)
    assert client.post("/plant-help/1/helpful/1").status_code == 404


# ---- deleting ----

def test_author_can_delete_own_answer_but_not_others(client):
    as_bob(client)
    ask(client)
    as_carol(client)
    answer(client)
    as_bob(client)
    assert client.post("/plant-help/answers/1/delete").status_code == 403
    as_carol(client)
    assert client.post("/plant-help/answers/1/delete").status_code == 302
    assert "No answers yet" in client.get("/plant-help/1").get_data(as_text=True)


def test_deleting_helpful_answer_clears_mark(client):
    as_bob(client)
    ask(client)
    answer(client)
    client.post("/plant-help/1/helpful/1")
    client.post("/plant-help/answers/1/delete")
    assert "✓ Helped" not in client.get("/plant-help/").get_data(as_text=True)


def test_admin_can_delete_any_question_and_answers_go_too(client):
    as_bob(client)
    ask(client)
    as_carol(client)
    answer(client)
    assert client.post("/plant-help/1/delete").status_code == 403
    as_alice(client)
    assert client.post("/plant-help/1/delete").status_code == 302
    assert client.get("/plant-help/1").status_code == 404
    as_carol(client)
    assert client.post("/plant-help/answers/1/delete").status_code == 404


def test_short_date_uses_local_time(monkeypatch):
    import time
    from content import short_date
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        assert short_date("2026-11-12 03:00:00") == "Nov 11, 2026"  # 7pm Pacific
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
