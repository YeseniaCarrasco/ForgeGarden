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
    assert "Not sure" in form and "Plant Doctor" not in form
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
        assert get_db().execute("SELECT COUNT(*) FROM plant_doctor").fetchone()[0] == 0


# ---- The request sent to Claude ----

def test_request_includes_photo_question_and_organic_rules(ai_app):
    fake = use_fake(ai_app, FakeMessages(GOOD_ANSWER))
    client = ai_app.test_client()
    login(client, "bob")
    ask(client, photo=photo())

    [req] = fake.requests
    assert req["model"] == "claude-opus-5-5"
    assert "CCOF" in req["system"] and "Never suggest synthetic" in req["system"]
    image, text = req["messages"][0]["content"]
    assert image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == PNG
    assert "<question>" in text["text"] and "Bugs on my roses" in text["text"]
    schema = req["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["topic"]["enum"] == ["wilting", "pests", "disease", "soil", "watering", "other"]
    assert req["fallbacks"] == "default"


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
