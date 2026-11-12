from datetime import date, time

import pytest

import volunteer
from app import create_app

TODAY = date(2026, 11, 11)  # a Wednesday


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": str(tmp_path / "test.db"),
        "TODAY": TODAY,
    })
    return app.test_client()


def login(client, username="alice", password="password123"):
    client.post("/login", data={"username": username, "password": password})


def sign_up(client, day, training=None):
    data = {"training_date": training} if training else {}
    return client.post(f"/calendar/compost/{day}", data=data)


# ---- schedule ----

def titles(day):
    return [o.title for o in volunteer.opportunities_for(day)]


def test_weekly_schedule():
    assert titles(date(2026, 11, 16)) == ["Compost Route", "Nourish Night Prep"]  # Mon
    assert titles(date(2026, 11, 17)) == ["Compost Route", "Glean Team", "Garden Work"]  # Tue
    assert titles(date(2026, 11, 18)) == ["Compost Route"]  # Wed
    assert titles(date(2026, 11, 20)) == ["Farmstand Harvest", "Compost Route", "Farmstand"]  # Fri


def test_time_labels():
    assert volunteer.COMPOST_ROUTE.time_label == "10:20am"
    assert volunteer.GLEAN_TEAM.time_label == "1–2pm"
    assert volunteer.GARDEN_WORK.time_label == "2:30–4pm"
    assert volunteer.FARMSTAND_HARVEST.time_label == "9:30–11:30am"
    assert volunteer.FARMSTAND.time_label == "11:30am–1:30pm"
    assert volunteer.NOURISH_PREP.time_label == "4:30–6pm"
    assert volunteer.fmt_range(time(12, 0)) == "12pm"


def test_kinds():
    assert volunteer.COMPOST_ROUTE.kind == volunteer.SIGN_UP
    assert volunteer.FARMSTAND.kind == volunteer.EVENT
    assert volunteer.GLEAN_TEAM.kind == volunteer.DROP_IN


def test_week_starts_on_sunday():
    assert volunteer.week_start(date(2026, 11, 11)) == date(2026, 11, 8)
    assert volunteer.week_start(date(2026, 11, 8)) == date(2026, 11, 8)
    assert volunteer.week_start(date(2026, 11, 14)) == date(2026, 11, 8)


def test_week_labels():
    assert volunteer.week_label(date(2026, 11, 8)) == "November 8–14, 2026"
    assert volunteer.week_label(date(2026, 11, 29)) == "Nov 29 – Dec 5, 2026"
    assert volunteer.week_label(date(2026, 12, 27)) == "Dec 27, 2026 – Jan 2, 2027"


def test_layout_places_blocks_by_time():
    blocks, columns = volunteer.layout_day(date(2026, 11, 17))  # Tuesday
    assert columns == "minmax(0, 1fr)"
    rows = {b["opp"].key: b["row"] for b in blocks}
    assert rows == {"compost": "9 / 13", "glean": "25 / 31", "garden": "34 / 43"}
    assert not any(b["stacked"] for b in blocks)


def test_layout_stacks_overlapping_blocks():
    blocks, columns = volunteer.layout_day(date(2026, 11, 13))  # Friday
    assert columns == "minmax(0, 1fr) minmax(0, 3fr)"
    placed = {b["opp"].key: (b["col"], b["stacked"]) for b in blocks}
    assert placed == {
        "harvest": ("1 / -1", False),
        "compost": ("2 / -1", True),   # drawn on top of the harvest block
        "farmstand": ("1 / -1", False),
    }


# ---- calendar page ----

def test_calendar_is_public(client):
    resp = client.get("/calendar")
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    for text in ["November 8–14, 2026", "Glean Team", "Garden Work", "Farmstand Harvest",
                 "Nourish Night Prep", "Compost Route", "no volunteers needed",
                 "asked to log in"]:
        assert text in page
    assert page.count('href="/calendar/compost/') == 4  # Wed 11 – Sat 14


def test_calendar_week_param(client):
    page = client.get("/calendar?week=2026-12-01").get_data(as_text=True)
    assert "Nov 29 – Dec 5, 2026" in page
    assert "Jump to this week" in page
    assert "week=2026-11-22" in page and "week=2026-12-06" in page


def test_calendar_bad_month_falls_back(client):
    assert "November 8–14, 2026" in client.get("/calendar?week=nope").get_data(as_text=True)


def test_links_to_calendar(client):
    assert b'href="/calendar"' in client.get("/").data
    login(client)
    assert b'href="/calendar"' in client.get("/dashboard").data


# ---- compost sign-up ----

def test_signup_requires_login(client):
    resp = client.get("/calendar/compost/2026-11-20")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_first_timer_must_pick_training_day(client):
    login(client)
    assert b"Training day" in client.get("/calendar/compost/2026-11-20").data
    resp = sign_up(client, "2026-11-20")
    assert resp.status_code == 400
    assert b"choose a training day" in resp.data


def test_training_day_must_be_before_route(client):
    login(client)
    for bad in ["2026-11-20", "2026-11-25", "2026-11-10"]:
        resp = sign_up(client, "2026-11-20", training=bad)
        assert resp.status_code == 400, bad


def test_first_timer_signup_and_calendar_status(client):
    login(client)
    resp = sign_up(client, "2026-11-20", training="2026-11-13")
    assert resp.status_code == 302
    assert b"You're signed up" in client.get("/calendar?week=2026-11-20").data
    dash = client.get("/dashboard").data
    assert b"Friday, November 20, 2026" in dash
    assert b"Training day: Friday, November 13, 2026" in dash


def test_returning_volunteer_skips_training(client):
    login(client)
    sign_up(client, "2026-11-20", training="2026-11-13")
    assert b"Training day" not in client.get("/calendar/compost/2026-11-22").data
    assert sign_up(client, "2026-11-22").status_code == 302


def test_one_volunteer_per_day(client):
    login(client)
    sign_up(client, "2026-11-20", training="2026-11-13")
    client.get("/logout")
    login(client, "bob", "builder456")
    assert b"Filled" in client.get("/calendar?week=2026-11-20").data
    assert b"already signed up" in client.get("/calendar/compost/2026-11-20").data
    sign_up(client, "2026-11-20", training="2026-11-13")
    client.get("/dashboard")  # clear flash message
    assert b"No upcoming sign-ups" in client.get("/dashboard").data


def test_cannot_sign_up_for_past_day(client):
    login(client)
    assert b"already passed" in client.get("/calendar/compost/2026-11-10").data


def test_first_timer_cannot_take_todays_route(client):
    login(client)
    assert b"need a training day before" in client.get("/calendar/compost/2026-11-11").data


def test_bad_date_is_404(client):
    login(client)
    assert client.get("/calendar/compost/not-a-date").status_code == 404


def test_cancel_signup(client):
    login(client)
    sign_up(client, "2026-11-20", training="2026-11-13")
    resp = client.post("/calendar/compost/2026-11-20/cancel")
    assert resp.status_code == 302
    dash = client.get("/dashboard").data
    assert b"Cancelled your compost route" in dash
    assert b"No upcoming sign-ups" in dash
    assert b'href="/calendar/compost/2026-11-20"' in client.get("/calendar?week=2026-11-20").data
