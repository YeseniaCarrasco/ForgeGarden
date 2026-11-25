import sqlite3

import pytest

from helpers import JPEG, PNG, login, make_app, photo, uploaded_files


@pytest.fixture
def client(tmp_path):
    return make_app(tmp_path).test_client()


def ask(client, **extra):
    data = {"topic": "pests", "title": "Holes in my kale", "body": "Tiny holes everywhere.", **extra}
    return client.post("/plant-help/ask", data=data, content_type="multipart/form-data")


# ---- Plant Help questions ----

def test_question_with_photo_is_saved_and_shown(client, tmp_path):
    login(client, "bob")
    r = ask(client, photo=photo())
    assert r.status_code == 302
    [key] = uploaded_files(tmp_path)
    assert key.endswith(".png")

    page = client.get("/plant-help/1").get_data(as_text=True)
    assert f"/photos/{key}" in page
    assert "📷" in client.get("/plant-help/").get_data(as_text=True)

    served = client.get(f"/photos/{key}")
    assert served.status_code == 200
    assert served.mimetype == "image/png"
    assert served.data == PNG


def test_question_without_photo_still_works(client, tmp_path):
    login(client, "bob")
    assert ask(client).status_code == 302
    assert uploaded_files(tmp_path) == []
    assert "/photos/" not in client.get("/plant-help/1").get_data(as_text=True)


def test_file_type_comes_from_contents_not_name(client, tmp_path):
    login(client, "bob")
    ask(client, photo=photo(JPEG, name="actually-a-jpeg.png"))
    [key] = uploaded_files(tmp_path)
    assert key.endswith(".jpg")


def test_non_image_upload_is_rejected(client, tmp_path):
    login(client, "bob")
    r = ask(client, photo=photo(b"<script>alert(1)</script>", name="evil.png"))
    assert r.status_code == 400
    assert "Photos must be JPEG, PNG, GIF, or WebP images." in r.get_data(as_text=True)
    assert uploaded_files(tmp_path) == []
    assert "No questions yet" in client.get("/plant-help/").get_data(as_text=True)


def test_photo_over_5_mb_is_rejected(client, tmp_path):
    login(client, "bob")
    r = ask(client, photo=photo(PNG + b"\x00" * (5 * 1024 * 1024)))
    assert r.status_code == 400
    assert "5 MB or smaller" in r.get_data(as_text=True)
    assert uploaded_files(tmp_path) == []


def test_deleting_question_deletes_its_photo(client, tmp_path):
    login(client, "bob")
    ask(client, photo=photo())
    assert len(uploaded_files(tmp_path)) == 1
    client.post("/plant-help/1/delete")
    assert uploaded_files(tmp_path) == []


@pytest.mark.parametrize("key", ["nope.png", "../test.db", "..%2Ftest.db", "a" * 32 + ".exe"])
def test_photo_route_only_serves_stored_photo_names(client, key):
    login(client, "bob")
    assert client.get(f"/photos/{key}").status_code == 404


# ---- Garden Journal ----

def journal_post(client, url="/journal/new", **extra):
    data = {"kind": "thought", "title": "Fall cover crops", "body": "Fava beans are in.", **extra}
    return client.post(url, data=data, content_type="multipart/form-data")


def test_manager_can_add_and_remove_journal_photo(client, tmp_path):
    login(client, "alice")
    journal_post(client, photo=photo())
    [key] = uploaded_files(tmp_path)
    assert f"/photos/{key}" in client.get("/journal/1").get_data(as_text=True)
    assert f"/photos/{key}" in client.get("/journal/").get_data(as_text=True)

    journal_post(client, url="/journal/1/edit", remove_photo="1")
    assert uploaded_files(tmp_path) == []
    assert "/photos/" not in client.get("/journal/1").get_data(as_text=True)


def test_replacing_journal_photo_deletes_the_old_one(client, tmp_path):
    login(client, "alice")
    journal_post(client, photo=photo(PNG))
    [old] = uploaded_files(tmp_path)
    journal_post(client, url="/journal/1/edit", photo=photo(JPEG, "new.jpg"))
    [new] = uploaded_files(tmp_path)
    assert new != old and new.endswith(".jpg")


def test_editing_journal_text_keeps_photo(client, tmp_path):
    login(client, "alice")
    journal_post(client, photo=photo())
    [key] = uploaded_files(tmp_path)
    journal_post(client, url="/journal/1/edit", title="Updated title")
    page = client.get("/journal/1").get_data(as_text=True)
    assert "Updated title" in page and f"/photos/{key}" in page


def test_old_database_gets_photo_columns(tmp_path):
    db_path = tmp_path / "test.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        "CREATE TABLE questions (id INTEGER PRIMARY KEY, username TEXT NOT NULL,"
        " topic TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,"
        " helpful_answer_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"
        "INSERT INTO questions (username, topic, title, body) VALUES ('bob', 'soil', 'Old question', 'From before photos.');"
    )
    con.commit()
    con.close()

    client = make_app(tmp_path).test_client()
    login(client, "bob")
    assert "Old question" in client.get("/plant-help/1").get_data(as_text=True)
    columns = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(questions)")}
    assert "photo_key" in columns
