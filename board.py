"""Plant Help board: community questions and answers about plant problems.

Anyone can read. Logged-in users can ask and answer. The person who asked
can mark one answer as the one that helped. Authors can delete their own
posts; the garden manager (admin) can delete any post.
"""
from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

from auth import is_admin, login_required
from content import clean
from db import get_db

bp = Blueprint("board", __name__, url_prefix="/plant-help")

TOPICS = {
    "wilting": "Wilting",
    "pests": "Pests",
    "disease": "Disease & Mold",
    "soil": "Soil & Compost",
    "watering": "Watering",
    "other": "Other",
}


def get_question(qid):
    row = get_db().execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    if row is None:
        abort(404)
    return row


def can_delete(username):
    return session.get("username") == username or is_admin()


@bp.route("/")
def index():
    topic = request.args.get("topic", "")
    if topic not in TOPICS:
        topic = ""
    sql = (
        "SELECT q.*, COUNT(a.id) AS answer_count FROM questions q"
        " LEFT JOIN answers a ON a.question_id = q.id"
    )
    params = ()
    if topic:
        sql += " WHERE q.topic = ?"
        params = (topic,)
    sql += " GROUP BY q.id ORDER BY q.id DESC"
    questions = get_db().execute(sql, params).fetchall()
    return render_template("board_index.html", questions=questions, topics=TOPICS, topic=topic)


@bp.route("/ask", methods=["GET", "POST"])
@login_required
def ask():
    errors = []
    if request.method == "POST":
        topic = request.form.get("topic", "")
        if topic not in TOPICS:
            errors.append("Please choose a topic.")
        title, err = clean(request.form, "title", "Title", 150)
        errors += [err] if err else []
        body, err = clean(request.form, "body", "Details", 5000)
        errors += [err] if err else []
        if not errors:
            db = get_db()
            cur = db.execute(
                "INSERT INTO questions (username, topic, title, body) VALUES (?, ?, ?, ?)",
                (session["username"], topic, title, body),
            )
            db.commit()
            flash("Your question is posted.", "success")
            return redirect(url_for("board.question", qid=cur.lastrowid))
    return render_template("board_ask.html", topics=TOPICS, errors=errors), (400 if errors else 200)


@bp.route("/<int:qid>")
def question(qid, answer_error=None):
    q = get_question(qid)
    answers = get_db().execute(
        "SELECT * FROM answers WHERE question_id = ? ORDER BY id", (qid,)
    ).fetchall()
    return render_template(
        "board_question.html", q=q, answers=answers, topics=TOPICS,
        can_delete=can_delete, answer_error=answer_error,
    )


@bp.route("/<int:qid>/answer", methods=["POST"])
@login_required
def answer(qid):
    get_question(qid)
    body, err = clean(request.form, "body", "Your answer", 5000)
    if err:
        return question(qid, answer_error=err), 400
    db = get_db()
    db.execute(
        "INSERT INTO answers (question_id, username, body) VALUES (?, ?, ?)",
        (qid, session["username"], body),
    )
    db.commit()
    flash("Thanks for helping!", "success")
    return redirect(url_for("board.question", qid=qid) + "#answers")


@bp.route("/<int:qid>/helpful/<int:aid>", methods=["POST"])
@login_required
def mark_helpful(qid, aid):
    q = get_question(qid)
    if q["username"] != session["username"]:
        abort(403)
    db = get_db()
    if db.execute(
        "SELECT 1 FROM answers WHERE id = ? AND question_id = ?", (aid, qid)
    ).fetchone() is None:
        abort(404)
    # Clicking the already-marked answer clears the mark.
    new_value = None if q["helpful_answer_id"] == aid else aid
    db.execute("UPDATE questions SET helpful_answer_id = ? WHERE id = ?", (new_value, qid))
    db.commit()
    return redirect(url_for("board.question", qid=qid) + "#answers")


@bp.route("/<int:qid>/delete", methods=["POST"])
@login_required
def delete_question(qid):
    q = get_question(qid)
    if not can_delete(q["username"]):
        abort(403)
    db = get_db()
    db.execute("DELETE FROM questions WHERE id = ?", (qid,))
    db.commit()
    flash("Question deleted.", "success")
    return redirect(url_for("board.index"))


@bp.route("/answers/<int:aid>/delete", methods=["POST"])
@login_required
def delete_answer(aid):
    db = get_db()
    a = db.execute("SELECT * FROM answers WHERE id = ?", (aid,)).fetchone()
    if a is None:
        abort(404)
    if not can_delete(a["username"]):
        abort(403)
    db.execute("DELETE FROM answers WHERE id = ?", (aid,))
    db.execute(
        "UPDATE questions SET helpful_answer_id = NULL WHERE id = ? AND helpful_answer_id = ?",
        (a["question_id"], aid),
    )
    db.commit()
    flash("Answer deleted.", "success")
    return redirect(url_for("board.question", qid=a["question_id"]) + "#answers")
