from types import SimpleNamespace

import anthropic
import pytest

import chatbot
from helpers import NEXT_FRIDAY, login, make_app


class FakeMessages:
    """Stands in for client.beta.messages: records requests, returns canned replies."""

    def __init__(self, replies=("Hello from the garden!",), stop_reason="end_turn", error=None):
        self.replies, self.stop_reason, self.error = list(replies), stop_reason, error
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        text = self.replies[min(len(self.requests), len(self.replies)) - 1]
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path, ANTHROPIC_API_KEY="test-key")


def use_fake(app, fake):
    app.extensions["anthropic_client"] = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    return fake


def send(client, message):
    return client.post("/garden-helper/", data={"message": message}, follow_redirects=True)


def test_requires_login(app):
    r = app.test_client().get("/garden-helper/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_conversation_round_trip(app):
    fake = use_fake(app, FakeMessages(["The farmstand is Fridays.", "You're welcome!"]))
    client = app.test_client()
    login(client, "bob")
    page = client.get("/garden-helper/").get_data(as_text=True)
    assert "Hi bob!" in page and "What&#39;s fresh at the farmstand" in page

    page = send(client, "When is the farmstand?").get_data(as_text=True)
    assert "When is the farmstand?" in page and "The farmstand is Fridays." in page
    page = send(client, "Thanks!").get_data(as_text=True)
    assert "You&#39;re welcome!" in page

    # The second request includes the whole conversation so far.
    roles = [m["role"] for m in fake.requests[1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert fake.requests[1]["model"] == "claude-sonnet-5-5"
    assert fake.requests[1]["fallbacks"] == "default"
    assert fake.requests[1]["betas"] == ["server-side-fallback-2026-07-01"]
    assert fake.requests[1]["output_config"] == {"effort": "low"}


def test_prompt_includes_real_garden_data(app):
    fake = use_fake(app, FakeMessages())
    client = app.test_client()
    login(client, "alice")
    client.post(f"/farmstand/{NEXT_FRIDAY}/items", data={"name": "Rainbow chard", "note": "$2 a bunch"})
    client.post(f"/farmstand/{NEXT_FRIDAY}/settings", data={"boxes": "5", "note": "Bring a bag!"})
    send(client, "What's fresh?")

    stable, this_week = (block["text"] for block in fake.requests[0]["system"])
    assert "CCOF" in stable and "Never make up dates" in stable
    assert "Today is Wednesday, November 18, 2026." in this_week
    assert "Friday, November 20, 2026" in this_week
    assert "Rainbow chard ($2 a bunch)" in this_week
    assert "5 of 5 produce boxes left." in this_week
    assert "Bring a bag!" in this_week
    assert "Compost Route" in this_week and "Glean Team" in this_week


def test_conversations_are_private(app):
    use_fake(app, FakeMessages(["Secret answer"]))
    bob = app.test_client()
    login(bob, "bob")
    send(bob, "Bob's private question")

    carol = app.test_client()
    login(carol, "carol")
    page = carol.get("/garden-helper/").get_data(as_text=True)
    assert "Bob&#39;s private question" not in page and "Secret answer" not in page


def test_new_chat_starts_fresh(app):
    fake = use_fake(app, FakeMessages(["First reply", "Second reply"]))
    client = app.test_client()
    login(client, "bob")
    send(client, "First question")
    client.post("/garden-helper/new")
    assert "First question" not in client.get("/garden-helper/").get_data(as_text=True)
    send(client, "Second question")
    assert len(fake.requests[1]["messages"]) == 1


def test_daily_limit(app, monkeypatch):
    monkeypatch.setattr(chatbot, "DAILY_LIMIT", 2)
    fake = use_fake(app, FakeMessages())
    client = app.test_client()
    login(client, "bob")
    send(client, "one")
    send(client, "two")
    page = send(client, "three").get_data(as_text=True)
    assert "reached today&#39;s limit of 2 messages" in page
    assert len(fake.requests) == 2


def test_daily_limit_counts_by_pacific_date(app, monkeypatch):
    from datetime import date, datetime

    from content import PACIFIC
    from db import get_db, utc_range_for_pacific_day

    # 5:30pm Pacific on Nov 24 is already Nov 25 in UTC.
    monkeypatch.setattr(chatbot, "pacific_now",
                        lambda: datetime(2026, 11, 24, 17, 30, tzinfo=PACIFIC))
    rows = [  # (username, role, created_at in UTC)
        ("bob", "user", "2026-11-24 08:00:00"),       # Nov 24, 12:00am PST: counts
        ("bob", "user", "2026-11-24 20:00:00"),       # Nov 24, noon: counts
        ("bob", "user", "2026-11-25 01:00:00"),       # Nov 24, 5pm (Nov 25 UTC): counts
        ("bob", "user", "2026-11-24 07:59:59"),       # Nov 23, 11:59pm: yesterday
        ("bob", "user", "2026-11-25 08:00:00"),       # Nov 25, 12:00am: tomorrow
        ("bob", "assistant", "2026-11-24 20:00:00"),  # Claude's replies don't count
        ("carol", "user", "2026-11-24 20:00:00"),     # someone else's message
    ]
    with app.app_context():
        db = get_db()
        for username, role, created_at in rows:
            db.execute(
                "INSERT INTO chat_messages (conversation_id, username, role, content, created_at)"
                " VALUES ('c1', %s, %s, 'hi', %s)", (username, role, created_at),
            )
        db.commit()
        # Counting by the UTC date (Nov 25) would give 2.
        assert chatbot.messages_sent_today("bob") == 3

        # Pacific days are 23 or 25 hours long when daylight saving time changes.
        assert utc_range_for_pacific_day(date(2026, 3, 8)) == ("2026-03-08 08:00:00", "2026-03-09 07:00:00")
        assert utc_range_for_pacific_day(date(2026, 11, 1)) == ("2026-11-01 07:00:00", "2026-11-02 08:00:00")

    # With a limit of 3, bob's next message is refused and Claude isn't called.
    monkeypatch.setattr(chatbot, "DAILY_LIMIT", 3)
    fake = use_fake(app, FakeMessages())
    client = app.test_client()
    login(client, "bob")
    page = send(client, "one more").get_data(as_text=True)
    assert "reached today&#39;s limit of 3 messages" in page
    assert fake.requests == []


@pytest.mark.parametrize("message, error", [("   ", "Your message is required."),
                                             ("x" * 1001, "1000 characters or fewer")])
def test_message_validation(app, message, error):
    fake = use_fake(app, FakeMessages())
    client = app.test_client()
    login(client, "bob")
    assert error in send(client, message).get_data(as_text=True)
    assert fake.requests == []


def test_api_failure_shows_friendly_error(app):
    error = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))
    use_fake(app, FakeMessages(error=error))
    client = app.test_client()
    login(client, "bob")
    assert "couldn&#39;t answer just now" in send(client, "Hello?").get_data(as_text=True)


def test_refusal_gets_polite_reply(app):
    use_fake(app, FakeMessages(stop_reason="refusal"))
    client = app.test_client()
    login(client, "bob")
    assert "I can answer questions about the" in send(client, "Something off-topic").get_data(as_text=True)


def test_ai_reply_html_is_escaped(app):
    use_fake(app, FakeMessages(["<script>alert(1)</script>"]))
    client = app.test_client()
    login(client, "bob")
    page = send(client, "hi").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_chat_off_without_api_key(tmp_path):
    client = make_app(tmp_path).test_client()
    login(client, "bob")
    page = client.get("/garden-helper/").get_data(as_text=True)
    assert "Garden Helper isn't available right now" in page
    r = client.post("/garden-helper/", data={"message": "hi"}, follow_redirects=True)
    assert r.status_code == 200
    assert "isn't available right now" in r.get_data(as_text=True)


@pytest.mark.parametrize("error", [
    anthropic.AuthenticationError(
        "bad key", response=SimpleNamespace(status_code=401, headers={}, request=None), body=None),
    anthropic.APITimeoutError(request=SimpleNamespace(method="POST", url="x")),
    RuntimeError("something unexpected"),
])
def test_any_ai_error_shows_friendly_message(app, error):
    use_fake(app, FakeMessages(error=error))
    client = app.test_client()
    login(client, "bob")
    r = send(client, "Hello?")
    assert r.status_code == 200
    assert "couldn&#39;t answer just now" in r.get_data(as_text=True)


def test_unreadable_response_shows_friendly_message(app):
    class Broken(FakeMessages):
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="end_turn", content=None)
    use_fake(app, Broken())
    client = app.test_client()
    login(client, "bob")
    r = send(client, "Hello?")
    assert r.status_code == 200 and "couldn&#39;t answer just now" in r.get_data(as_text=True)
