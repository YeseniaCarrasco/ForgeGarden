"""Friday Farmstand: what's freshly harvested this week, and produce box reservations.

Anyone can see the harvest list. Logged-in users can reserve one produce box
per farmstand day while boxes are left, and cancel it before the day passes.
The garden manager (admin) lists harvested items (with optional photos), sets
how many boxes are available, and sees who reserved one.
"""
from datetime import date, timedelta

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

import storage
import volunteer
from auth import admin_required, is_admin, login_required
from content import clean, local_path
from db import IntegrityError, current_date, get_db

bp = Blueprint("farmstand", __name__, url_prefix="/farmstand")

FRIDAY = 4
MAX_BOXES = 200


def next_farmstand(day):
    """The farmstand Friday on or after `day`."""
    return day + timedelta(days=(FRIDAY - day.weekday()) % 7)


def parse_farmstand_date(text):
    try:
        day = date.fromisoformat(text)
    except ValueError:
        abort(404)
    if day.weekday() != FRIDAY:
        abort(404)
    return day


def box_counts(db, day):
    """(boxes offered, boxes reserved) for a farmstand day."""
    row = db.execute(
        "SELECT boxes FROM farmstand_days WHERE farmstand_date = %s", (day.isoformat(),)
    ).fetchone()
    reserved = db.execute(
        "SELECT COUNT(*) AS n FROM box_reservations WHERE farmstand_date = %s", (day.isoformat(),)
    ).fetchone()["n"]
    return (row["boxes"] if row else 0), reserved


def back(day):
    return redirect(url_for("farmstand.index", day=day.isoformat()))


@bp.route("/")
def index():
    today = current_date()
    try:
        day = next_farmstand(date.fromisoformat(request.args.get("day", "")))
    except ValueError:
        day = next_farmstand(today)
    db = get_db()
    settings = db.execute(
        "SELECT * FROM farmstand_days WHERE farmstand_date = %s", (day.isoformat(),)
    ).fetchone()
    items = db.execute(
        "SELECT * FROM harvest_items WHERE farmstand_date = %s ORDER BY id", (day.isoformat(),)
    ).fetchall()
    boxes, reserved = box_counts(db, day)
    username = session.get("username")
    mine = username and db.execute(
        "SELECT 1 FROM box_reservations WHERE farmstand_date = %s AND username = %s",
        (day.isoformat(), username),
    ).fetchone() is not None
    reservations = []
    if is_admin():
        reservations = db.execute(
            "SELECT username, created_at FROM box_reservations"
            " WHERE farmstand_date = %s ORDER BY id", (day.isoformat(),),
        ).fetchall()
    return render_template(
        "farmstand.html",
        day=day,
        is_past=day < today,
        is_next=day == next_farmstand(today),
        note=settings["note"] if settings else "",
        items=items,
        boxes=boxes,
        reserved=reserved,
        left=max(boxes - reserved, 0),
        mine=mine,
        reservations=reservations,
        farmstand=volunteer.FARMSTAND,
        prev_day=(day - timedelta(days=7)).isoformat(),
        next_day=(day + timedelta(days=7)).isoformat(),
        max_boxes=MAX_BOXES,
    )


@bp.route("/<day>/reserve", methods=["POST"])
@login_required
def reserve(day):
    day = parse_farmstand_date(day)
    if day < current_date():
        flash("That farmstand has already happened.", "error")
        return back(day)
    db = get_db()
    already = db.execute(
        "SELECT 1 FROM box_reservations WHERE farmstand_date = %s AND username = %s",
        (day.isoformat(), session["username"]),
    ).fetchone()
    if already:
        flash("You already have a box reserved for this farmstand.", "error")
        return back(day)
    try:
        # Lock this day's row first, so two people can't both take the last box.
        db.execute(
            "SELECT boxes FROM farmstand_days WHERE farmstand_date = %s FOR UPDATE",
            (day.isoformat(),),
        )
        added = db.execute(
            "INSERT INTO box_reservations (farmstand_date, username)"
            " SELECT %s, %s WHERE (SELECT COUNT(*) FROM box_reservations WHERE farmstand_date = %s)"
            " < (SELECT COALESCE(MAX(boxes), 0) FROM farmstand_days WHERE farmstand_date = %s)",
            (day.isoformat(), session["username"], day.isoformat(), day.isoformat()),
        ).rowcount
        db.commit()
    except IntegrityError:  # UNIQUE (farmstand_date, username)
        db.rollback()
        flash("You already have a box reserved for this farmstand.", "error")
        return back(day)
    if added:
        flash(f"Your produce box is reserved for {volunteer.long_date(day)}. "
              "Pick it up at the farmstand.", "success")
    else:
        flash("Sorry, all the produce boxes for that day are reserved.", "error")
    return back(day)


@bp.route("/<day>/cancel", methods=["POST"])
@login_required
def cancel(day):
    day = parse_farmstand_date(day)
    if day < current_date():
        flash("Past reservations can't be cancelled.", "error")
        return back(day)
    db = get_db()
    deleted = db.execute(
        "DELETE FROM box_reservations WHERE farmstand_date = %s AND username = %s",
        (day.isoformat(), session["username"]),
    ).rowcount
    db.commit()
    if deleted:
        flash("Your produce box reservation is cancelled.", "success")
    else:
        flash("You didn't have a box reserved for that day.", "error")
    # Only allow paths on this site (the dashboard sends one) to avoid open redirects.
    next_url = local_path(request.form.get("next", ""))
    if next_url:
        return redirect(next_url)
    return back(day)


@bp.route("/<day>/settings", methods=["POST"])
@admin_required
def settings(day):
    day = parse_farmstand_date(day)
    db = get_db()
    _, reserved = box_counts(db, day)
    note, err = clean(request.form, "note", "Note", 300, required=False)
    try:
        boxes = int(request.form.get("boxes", ""))
    except ValueError:
        boxes = None
    if err:
        flash(err, "error")
    elif boxes is None or not 0 <= boxes <= MAX_BOXES:
        flash(f"Number of boxes must be a whole number from 0 to {MAX_BOXES}.", "error")
    elif boxes < reserved:
        flash(f"{reserved} boxes are already reserved, so you can't offer fewer than that.", "error")
    else:
        db.execute(
            "INSERT INTO farmstand_days (farmstand_date, boxes, note) VALUES (%s, %s, %s)"
            " ON CONFLICT (farmstand_date) DO UPDATE SET boxes = excluded.boxes, note = excluded.note",
            (day.isoformat(), boxes, note or None),
        )
        db.commit()
        flash("Farmstand details saved.", "success")
    return back(day)


@bp.route("/<day>/items", methods=["POST"])
@admin_required
def add_item(day):
    day = parse_farmstand_date(day)
    errors = []
    name, err = clean(request.form, "name", "Item name", 100)
    errors += [err] if err else []
    note, err = clean(request.form, "note", "Details", 200, required=False)
    errors += [err] if err else []
    try:
        upload = storage.read_upload(request.files.get("photo"))
    except storage.PhotoError as e:
        errors.append(str(e))
        upload = None
    if errors:
        for e in errors:
            flash(e, "error")
        return back(day)
    photo_key = storage.save_photo(*upload) if upload else None
    db = get_db()
    db.execute(
        "INSERT INTO harvest_items (farmstand_date, name, note, photo_key) VALUES (%s, %s, %s, %s)",
        (day.isoformat(), name, note or None, photo_key),
    )
    db.commit()
    flash(f"Added {name} to the harvest list.", "success")
    return back(day)


@bp.route("/items/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM harvest_items WHERE id = %s", (item_id,)).fetchone()
    if item is None:
        abort(404)
    db.execute("DELETE FROM harvest_items WHERE id = %s", (item_id,))
    db.commit()
    storage.delete_photo(item["photo_key"])
    flash(f"Removed {item['name']} from the harvest list.", "success")
    return back(date.fromisoformat(item["farmstand_date"]))
