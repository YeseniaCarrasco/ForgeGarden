"""Plant Help board: community questions and answers about plant problems.

Anyone can read. Logged-in users can ask and answer, and can attach a photo
to a question. The person who asked can mark one answer as the one that
helped. Authors can delete their own posts; the garden manager (admin) can
delete any post.

When the Plant Doctor (AI) is on, each new question gets an AI first take:
a suggested topic, likely causes, and an organic treatment draft.
"""
import json

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

import plant_doctor
import storage
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
# "Not sure" on the ask form: the Plant Doctor picks the topic (or "Other" if it's off).
NOT_SURE = "auto"


def get_question(qid):
    row = get_db().execute("SELECT * FROM questions WHERE id = %s", (qid,)).fetchone()
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
        sql += " WHERE q.topic = %s"
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
        if topic not in TOPICS and topic != NOT_SURE:
            errors.append("Please choose a topic.")
        title, err = clean(request.form, "title", "Title", 150)
        errors += [err] if err else []
        body, err = clean(request.form, "body", "Details", 5000)
        errors += [err] if err else []
        try:
            upload = storage.read_upload(request.files.get("photo"))
        except storage.PhotoError as e:
            errors.append(f"{e} Please choose the photo again.")
            upload = None
        if not errors:
            photo_key = storage.save_photo(*upload) if upload else None
            db = get_db()
            cur = db.execute(
                "INSERT INTO questions (username, topic, title, body, photo_key)"
                " VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (session["username"], "other" if topic == NOT_SURE else topic,
                 title, body, photo_key),
            )
            qid = cur.fetchone()["id"]
            db.commit()
            run_plant_doctor(qid, title, body, upload, let_ai_pick_topic=topic == NOT_SURE)
            flash("Your question is posted.", "success")
            return redirect(url_for("board.question", qid=qid))
    return render_template(
        "board_ask.html", topics=TOPICS, not_sure=NOT_SURE, errors=errors,
        plant_doctor_on=plant_doctor.is_enabled(),
    ), (400 if errors else 200)


def run_plant_doctor(qid, title, body, upload, let_ai_pick_topic):
    """Save the AI's first take for a new question, if the Plant Doctor is on."""
    photo = (upload[0], storage.MEDIA_TYPES[upload[1]]) if upload else None
    diagnosis = plant_doctor.diagnose(title, body, photo)
    if diagnosis is None:
        return
    db = get_db()
    db.execute(
        "INSERT INTO plant_doctor"
        " (question_id, topic, likely_issues, organic_treatment) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (question_id) DO UPDATE SET topic = excluded.topic,"
        " likely_issues = excluded.likely_issues,"
        " organic_treatment = excluded.organic_treatment, created_at = excluded.created_at",
        (qid, *plant_doctor.to_row(diagnosis)),
    )
    if let_ai_pick_topic:
        db.execute("UPDATE questions SET topic = %s WHERE id = %s", (diagnosis.topic, qid))
    db.commit()


@bp.route("/<int:qid>")
def question(qid, answer_error=None):
    q = get_question(qid)
    db = get_db()
    answers = db.execute(
        "SELECT * FROM answers WHERE question_id = %s ORDER BY id", (qid,)
    ).fetchall()
    ai = db.execute("SELECT * FROM plant_doctor WHERE question_id = %s", (qid,)).fetchone()
    if ai:
        ai = {**dict(ai), "likely_issues": json.loads(ai["likely_issues"])}
    return render_template(
        "board_question.html", q=q, answers=answers, topics=TOPICS, ai=ai,
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
        "INSERT INTO answers (question_id, username, body) VALUES (%s, %s, %s)",
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
        "SELECT 1 FROM answers WHERE id = %s AND question_id = %s", (aid, qid)
    ).fetchone() is None:
        abort(404)
    # Clicking the already-marked answer clears the mark.
    new_value = None if q["helpful_answer_id"] == aid else aid
    db.execute("UPDATE questions SET helpful_answer_id = %s WHERE id = %s", (new_value, qid))
    db.commit()
    return redirect(url_for("board.question", qid=qid) + "#answers")


@bp.route("/<int:qid>/delete", methods=["POST"])
@login_required
def delete_question(qid):
    q = get_question(qid)
    if not can_delete(q["username"]):
        abort(403)
    db = get_db()
    db.execute("DELETE FROM questions WHERE id = %s", (qid,))
    db.commit()
    storage.delete_photo(q["photo_key"])
    flash("Question deleted.", "success")
    return redirect(url_for("board.index"))


@bp.route("/answers/<int:aid>/delete", methods=["POST"])
@login_required
def delete_answer(aid):
    db = get_db()
    a = db.execute("SELECT * FROM answers WHERE id = %s", (aid,)).fetchone()
    if a is None:
        abort(404)
    if not can_delete(a["username"]):
        abort(403)
    db.execute("DELETE FROM answers WHERE id = %s", (aid,))
    db.execute(
        "UPDATE questions SET helpful_answer_id = NULL WHERE id = %s AND helpful_answer_id = %s",
        (a["question_id"], aid),
    )
    db.commit()
    flash("Answer deleted.", "success")
    return redirect(url_for("board.question", qid=a["question_id"]) + "#answers")
