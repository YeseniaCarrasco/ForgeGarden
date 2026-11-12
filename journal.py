"""Garden Journal: posts from the garden manager.

Anyone can read. Only the garden manager (admin) can write, edit, or delete.
A post is either a "thought" or a "reading" (something to read, with an
optional link). This is separate from any future announcements page.
"""
from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

from auth import admin_required
from content import clean, clean_url, excerpt
from db import get_db

bp = Blueprint("journal", __name__, url_prefix="/journal")

KINDS = {"thought": "Thought", "reading": "Reading"}


def get_post(pid):
    row = get_db().execute("SELECT * FROM journal_posts WHERE id = ?", (pid,)).fetchone()
    if row is None:
        abort(404)
    return row


def read_form():
    """Validate the post form. Returns (values, errors)."""
    form = request.form
    values, errors = {}, []
    values["kind"] = form.get("kind", "")
    if values["kind"] not in KINDS:
        errors.append("Please choose a post type.")
    for field, label, max_len, required in [
        ("title", "Title", 150, True),
        ("body", "Post", 20000, True),
        ("link_title", "Reading title", 200, False),
    ]:
        values[field], err = clean(form, field, label, max_len, required)
        errors += [err] if err else []
    values["link_url"], err = clean_url(form, "link_url", "Link")
    errors += [err] if err else []
    return values, errors


@bp.route("/")
def index():
    kind = request.args.get("kind", "")
    if kind not in KINDS:
        kind = ""
    sql = "SELECT * FROM journal_posts"
    params = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    posts = get_db().execute(sql + " ORDER BY id DESC", params).fetchall()
    return render_template(
        "journal_index.html", posts=posts, kinds=KINDS, kind=kind, excerpt=excerpt,
    )


@bp.route("/<int:pid>")
def post(pid):
    return render_template("journal_post.html", post=get_post(pid), kinds=KINDS)


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    values, errors = {"kind": "thought"}, []
    if request.method == "POST":
        values, errors = read_form()
        if not errors:
            db = get_db()
            cur = db.execute(
                "INSERT INTO journal_posts (username, kind, title, body, link_url, link_title)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session["username"], values["kind"], values["title"], values["body"],
                 values["link_url"] or None, values["link_title"] or None),
            )
            db.commit()
            flash("Journal post published.", "success")
            return redirect(url_for("journal.post", pid=cur.lastrowid))
    return render_template(
        "journal_form.html", values=values, errors=errors, kinds=KINDS, editing=None,
    ), (400 if errors else 200)


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def edit(pid):
    existing = get_post(pid)
    values, errors = dict(existing), []
    if request.method == "POST":
        values, errors = read_form()
        if not errors:
            db = get_db()
            db.execute(
                "UPDATE journal_posts SET kind = ?, title = ?, body = ?, link_url = ?,"
                " link_title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (values["kind"], values["title"], values["body"],
                 values["link_url"] or None, values["link_title"] or None, pid),
            )
            db.commit()
            flash("Journal post updated.", "success")
            return redirect(url_for("journal.post", pid=pid))
    return render_template(
        "journal_form.html", values=values, errors=errors, kinds=KINDS, editing=existing,
    ), (400 if errors else 200)


@bp.route("/<int:pid>/delete", methods=["POST"])
@admin_required
def delete(pid):
    get_post(pid)
    db = get_db()
    db.execute("DELETE FROM journal_posts WHERE id = ?", (pid,))
    db.commit()
    flash("Journal post deleted.", "success")
    return redirect(url_for("journal.index"))
