import pytest

from helpers import NEXT_FRIDAY, login, make_app, photo, uploaded_files


@pytest.fixture
def client(tmp_path):
    return make_app(tmp_path).test_client()


def set_boxes(client, boxes, note="", day=NEXT_FRIDAY):
    return client.post(f"/farmstand/{day}/settings", data={"boxes": str(boxes), "note": note})


def reserve(client, day=NEXT_FRIDAY):
    return client.post(f"/farmstand/{day}/reserve", follow_redirects=True).get_data(as_text=True)


def test_page_is_viewable_logged_out(client):
    login(client, "alice")
    set_boxes(client, 3)
    client.post(f"/farmstand/{NEXT_FRIDAY}/items", data={"name": "Kale"})
    client.post("/logout")
    page = client.get("/farmstand/").get_data(as_text=True)
    assert "Kale" in page and "of 3 boxes left" in page
    assert "Log in to reserve a box" in page
    assert "Garden manager" not in page and "Remove" not in page


def test_page_shows_next_friday(client):
    login(client, "bob")
    page = client.get("/farmstand/").get_data(as_text=True)
    assert "Friday, November 20, 2026" in page
    assert "Next farmstand" in page
    assert "harvest list isn&#39;t posted yet" in page or "harvest list isn't posted yet" in page
    assert "Garden manager" not in page


def test_any_date_shows_that_weeks_farmstand(client):
    login(client, "bob")
    page = client.get("/farmstand/?day=2026-11-23").get_data(as_text=True)
    assert "Friday, November 27, 2026" in page


def test_manager_lists_harvest_with_photo(client, tmp_path):
    login(client, "alice")
    client.post(f"/farmstand/{NEXT_FRIDAY}/items",
                data={"name": "Rainbow chard", "note": "$2 a bunch", "photo": photo()},
                content_type="multipart/form-data")
    [key] = uploaded_files(tmp_path)

    login(client, "bob")
    page = client.get("/farmstand/").get_data(as_text=True)
    assert "Rainbow chard" in page and "$2 a bunch" in page
    assert f"/photos/{key}" in page
    assert "Remove" not in page


def test_manager_can_remove_item_and_its_photo(client, tmp_path):
    login(client, "alice")
    client.post(f"/farmstand/{NEXT_FRIDAY}/items", data={"name": "Kale", "photo": photo()},
                content_type="multipart/form-data")
    page = client.post("/farmstand/items/1/delete", follow_redirects=True).get_data(as_text=True)
    assert "Removed Kale from the harvest list." in page
    assert "Kale" not in client.get("/farmstand/").get_data(as_text=True)
    assert uploaded_files(tmp_path) == []


@pytest.mark.parametrize("url", [
    f"/farmstand/{NEXT_FRIDAY}/items",
    f"/farmstand/{NEXT_FRIDAY}/settings",
    "/farmstand/items/1/delete",
])
def test_only_manager_can_change_farmstand(client, url):
    login(client, "bob")
    assert client.post(url, data={"name": "Kale", "boxes": "5"}).status_code == 403


def test_reservations_respect_box_limit(client):
    login(client, "alice")
    set_boxes(client, 1, note="Bring a bag!")

    login(client, "bob")
    page = client.get("/farmstand/").get_data(as_text=True)
    assert "Bring a bag!" in page and "of 1 box left" in page
    assert "Your produce box is reserved" in reserve(client)
    assert "You already have a box reserved" in reserve(client)

    login(client, "carol")
    assert "all the produce boxes for that day are reserved" in reserve(client)

    login(client, "bob")
    client.post(f"/farmstand/{NEXT_FRIDAY}/cancel")
    login(client, "carol")
    assert "Your produce box is reserved" in reserve(client)

    login(client, "alice")
    page = client.get("/farmstand/").get_data(as_text=True)
    assert "Reservations (1)" in page and "<li>carol</li>" in page


def test_no_reservations_when_no_boxes_offered(client):
    login(client, "bob")
    assert "all the produce boxes for that day are reserved" in reserve(client)


def test_manager_cannot_offer_fewer_boxes_than_reserved(client):
    login(client, "alice")
    set_boxes(client, 2)
    reserve(client)
    login(client, "bob")
    reserve(client)
    login(client, "alice")
    r = client.post(f"/farmstand/{NEXT_FRIDAY}/settings", data={"boxes": "1"}, follow_redirects=True)
    assert "2 boxes are already reserved" in r.get_data(as_text=True)


@pytest.mark.parametrize("boxes", ["-1", "201", "lots", ""])
def test_box_count_must_be_valid(client, boxes):
    login(client, "alice")
    r = client.post(f"/farmstand/{NEXT_FRIDAY}/settings", data={"boxes": boxes}, follow_redirects=True)
    assert "whole number from 0 to 200" in r.get_data(as_text=True)


def test_past_and_non_friday_dates(client):
    login(client, "alice")
    set_boxes(client, 5, day="2026-11-13")
    login(client, "bob")
    assert "already happened" in reserve(client, day="2026-11-13")
    assert client.post("/farmstand/2026-11-19/reserve").status_code == 404  # a Thursday
    assert client.post("/farmstand/not-a-date/reserve").status_code == 404


def test_reservation_shows_on_dashboard_and_can_be_cancelled_there(client):
    login(client, "alice")
    set_boxes(client, 3)
    login(client, "bob")
    reserve(client)
    page = client.get("/dashboard").get_data(as_text=True)
    assert "Your produce boxes" in page and "Friday, November 20, 2026" in page

    r = client.post(f"/farmstand/{NEXT_FRIDAY}/cancel", data={"next": "/dashboard"})
    assert r.headers["Location"].endswith("/dashboard")
    assert "No produce boxes reserved" in client.get("/dashboard").get_data(as_text=True)


def test_cancel_does_not_redirect_off_site(client):
    login(client, "bob")
    r = client.post(f"/farmstand/{NEXT_FRIDAY}/cancel", data={"next": "//evil.example.com"})
    assert "evil.example.com" not in r.headers["Location"]


def test_logged_out_visitor_cannot_reserve(client):
    r = client.post(f"/farmstand/{NEXT_FRIDAY}/reserve")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
