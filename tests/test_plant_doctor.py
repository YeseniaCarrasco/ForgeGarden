import base64
import json
from types import SimpleNamespace

import anthropic
import pytest

import plant_doctor
from helpers import PNG, login, make_app, photo

GOOD_ANSWER = {
    "topic": "pests",
    "likely_issues": ["Aphids: clusters of tiny green insects under the leaves."],
    "organic_treatment": "Knock them off with a strong spray of water.\n\nThen try insecticidal soap.",
}


class FakeMessages:
    """Stands in for client.beta.messages and records each request."""

    def __init__(self, reply=None, stop_reason="end_turn", error=None):
        self.reply, self.stop_reason, self.error = reply, stop_reason, error
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        text = json.dumps(self.reply) if isinstance(self.reply, dict) else self.reply
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=text)],
        )


@pytest.fixture
def ai_app(tmp_path):
    return make_app(tmp_path, ANTHROPIC_API_KEY="test-key")


def use_fake(app, messages):
    app.extensions["anthropic_client"] = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return messages


def ask(client, topic="auto", **extra):
    data = {"topic": topic, "title": "Bugs on my roses", "body": "Little green bugs.", **extra}
    return client.post("/plant-help/ask", data=data, content_type="multipart/form-data")


# ---- On the board ----

def test_plant_doctor_draft_appears_and_picks_topic(ai_app):
    use_fake(ai_app, FakeMessages(GOOD_ANSWER))
    client = ai_app.test_client()
    login(client, "bob")
    assert ask(client, topic="auto").status_code == 302

    page = client.get("/plant-help/1").get_data(as_text=True)
    assert "Plant Doctor&#39;s first take" in page or "Plant Doctor's first take" in page
    assert "AI-generated draft" in page
    assert "Aphids: clusters of tiny green insects" in page
    assert "Then try insecticidal soap." in page
    # "Not sure" questions get the AI's topic.
    assert "Bugs on my roses" in client.get("/plant-help/?topic=pests").get_data(as_text=True)


def test_topic_chosen_by_asker_is_kept(ai_app):
    use_fake(ai_app, FakeMessages(GOOD_ANSWER))
    client = ai_app.test_client()
    login(client, "bob")
    ask(client, topic="wilting")
    assert "Bugs on my roses" in client.get("/plant-help/?topic=wilting").get_data(as_text=True)
    assert "Bugs on my roses" not in client.get("/plant-help/?topic=pests").get_data(as_text=True)


def test_question_still_posts_when_ai_fails(ai_app):
    error = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))
    use_fake(ai_app, FakeMessages(error=error))
    client = ai_app.test_client()
    login(client, "bob")
    assert ask(client, topic="auto").status_code == 302
    page = client.get("/plant-help/1").get_data(as_text=True)
    assert "Bugs on my roses" in page
    assert "AI-generated draft" not in page
    assert "Bugs on my roses" in client.get("/plant-help/?topic=other").get_data(as_text=True)


def test_plant_doctor_off_without_api_key(tmp_path):
    client = make_app(tmp_path).test_client()
    login(client, "bob")
    form = client.get("/plant-help/ask").get_data(as_text=True)
    assert "Not sure" in form and "Plant Doctor will suggest" not in form
    assert "Plant Doctor isn't available right now" in form
    ask(client, topic="auto")
    assert "AI-generated draft" not in client.get("/plant-help/1").get_data(as_text=True)


def test_ai_draft_is_deleted_with_question(ai_app):
    use_fake(ai_app, FakeMessages(GOOD_ANSWER))
    client = ai_app.test_client()
    login(client, "bob")
    ask(client)
    client.post("/plant-help/1/delete")
    with ai_app.app_context():
        from db import get_db
        assert get_db().execute("SELECT COUNT(*) AS n FROM plant_doctor").fetchone()["n"] == 0


# ---- The request sent to Claude ----

def test_request_includes_photo_question_and_organic_rules(ai_app):
    fake = use_fake(ai_app, FakeMessages(GOOD_ANSWER))
    client = ai_app.test_client()
    login(client, "bob")
    ask(client, photo=photo())

    [req] = fake.requests
    assert req["model"] == "claude-sonnet-5-5"
    assert "CCOF" in req["system"] and "Never suggest synthetic" in req["system"]
    image, text = req["messages"][0]["content"]
    assert image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == PNG
    assert "<question>" in text["text"] and "Bugs on my roses" in text["text"]
    schema = req["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["topic"]["enum"] == ["wilting", "pests", "disease", "soil", "watering", "other"]
    assert req["fallbacks"] == "default"  # server-side refusal fallback, chosen by the API
    assert req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["output_config"]["effort"] == "medium"


@pytest.mark.parametrize("reply, stop_reason", [
    (GOOD_ANSWER, "refusal"),
    (GOOD_ANSWER, "max_tokens"),
    ("not json", "end_turn"),
    ({**GOOD_ANSWER, "topic": "aliens"}, "end_turn"),
])
def test_unusable_responses_are_ignored(ai_app, reply, stop_reason):
    use_fake(ai_app, FakeMessages(reply, stop_reason=stop_reason))
    with ai_app.app_context():
        assert plant_doctor.diagnose("Title", "Body") is None


# ---- Claude API setup ----

def test_client_uses_api_key_timeout_and_retries(tmp_path):
    from anthropic import Anthropic

    app = make_app(tmp_path, ANTHROPIC_API_KEY="test-key")
    with app.app_context():
        client = plant_doctor.get_client()
        assert isinstance(client, Anthropic)
        assert client.api_key == "test-key"
        assert client.timeout == 60.0
        assert client.max_retries == 1
        assert plant_doctor.get_client() is client  # one shared client


def test_api_key_comes_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", " env-key ")
    app = make_app(tmp_path)
    assert app.config["ANTHROPIC_API_KEY"] == "env-key"
    with app.app_context():
        assert plant_doctor.is_enabled()


def test_no_vertex_settings_left():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for path in [*root.glob("*.py"), *root.glob("templates/*.html"), root / "README.md"]:
        text = path.read_text()
        assert "VERTEX" not in text and "AnthropicVertex" not in text, path.name


@pytest.mark.parametrize("error", [
    anthropic.AuthenticationError(
        "bad key", response=SimpleNamespace(status_code=401, headers={}, request=None), body=None),
    anthropic.RateLimitError(
        "slow down", response=SimpleNamespace(status_code=429, headers={}, request=None), body=None),
    anthropic.APITimeoutError(request=SimpleNamespace(method="POST", url="x")),
    RuntimeError("something unexpected"),
])
def test_any_ai_error_still_posts_question(ai_app, error):
    use_fake(ai_app, FakeMessages(error=error))
    client = ai_app.test_client()
    login(client, "bob")
    assert ask(client).status_code == 302
    page = client.get("/plant-help/1")
    assert page.status_code == 200
    assert "AI-generated draft" not in page.get_data(as_text=True)


def test_unreadable_response_is_ignored(ai_app):
    class Broken(FakeMessages):
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="end_turn", content=None)
    use_fake(ai_app, Broken())
    with ai_app.app_context():
        assert plant_doctor.diagnose("Title", "Body") is None


def test_real_api_is_never_called(ai_app):
    # No fake client: the real SDK client is built, and the test backstop stops the request.
    with ai_app.app_context():
        assert plant_doctor.diagnose("Title", "Body") is None
