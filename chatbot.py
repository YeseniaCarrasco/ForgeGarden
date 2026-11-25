"""Garden Helper: an AI chatbot (Claude) for questions about the Forge Garden.

Logged-in users can ask about volunteering, the farmstand, the garden itself,
and organic growing. Each answer is grounded in the garden's real schedule and
this week's farmstand listing, which are put into the prompt on every request.

Conversations are saved in the database (one per browser session, until the
user starts a new chat). Each user can send DAILY_LIMIT messages a day, to keep
API costs predictable. Claude is called through Google Cloud Vertex AI; the
chat is on only when VERTEX_PROJECT_ID is set.
"""
import uuid

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, session, url_for,
)

import farmstand
import plant_doctor
import volunteer
from auth import login_required
from content import clean
from db import TODAY_TEXT, current_date, get_db

bp = Blueprint("chat", __name__, url_prefix="/garden-helper")

MODEL = plant_doctor.MODEL
DAILY_LIMIT = 40
HISTORY_MESSAGES = 20  # how many earlier messages Claude sees
MAX_MESSAGE_CHARS = 1000

SUGGESTIONS = [
    "What's fresh at the farmstand this Friday?",
    "How do I sign up for the compost route?",
    "When can I drop in to volunteer?",
    "How do I keep aphids off kale organically?",
]

SYSTEM_PROMPT = """\
You are the Garden Helper, a friendly chatbot on the Forge Garden website. \
The Forge Garden is Santa Clara University's organic campus garden, run by \
the Center for Sustainability. You answer questions from students, \
volunteers, and neighbors.

What you help with:
- Volunteering: when and how to help, using the schedule below.
- The Friday Farmstand: hours, what's fresh this week, and produce boxes.
- The garden itself: what it has, its history, and its program goals.
- Gardening questions, answered with organic methods only. The garden is \
CCOF-certified organic, so never suggest synthetic pesticides, herbicides, \
or fertilizers.
- Finding things on this website (the pages are listed below).

How to answer:
- Keep replies short: usually 2-5 sentences, or a short list.
- Write plain text. Don't use Markdown headings, bold, or tables. For a \
list, start each line with "- ".
- Only state garden facts that appear below. If you don't know something \
(like a staff member's name, an exact policy, or anything not listed), say \
so and suggest asking on the Plant Help board or checking with the garden \
manager. Never make up dates, prices, or rules.
- For a specific sick plant, give general organic tips and suggest posting \
on the Plant Help board with a photo, where the Plant Doctor and the garden \
manager can see it.
- If someone asks about something unrelated to the garden, gardening, food, \
or sustainability, politely say you can only help with garden topics.

Pages on this website:
- Volunteer Calendar (/calendar): weekly schedule; log in to sign up for the \
compost route.
- Plant Help (/plant-help/): ask plant questions, optionally with a photo.
- Farmstand (/farmstand/): this week's harvest and produce box reservations.
- Garden Journal (/journal/): posts from the garden manager.
- Dashboard (/dashboard): your compost routes and produce boxes.

About the Forge Garden:
- A half-acre edible, organic garden and a hub for sustainable food system \
education, established in 2008.
- It has chickens, an apiary, a 400-square-foot greenhouse, a compost \
center, over 20 fruit trees, over 15,000 square feet of garden beds, an \
outdoor kitchen, and the 2007 Solar Decathlon House, used as a public commons.
- Certified organic through California Certified Organic Farmers (CCOF).
- Program goals: education through the garden as a living lab; community \
resilience through produce donation, food education, the farmstand, and \
neighborhood collaboration; and a just, sustainable food system.

Compost route sign-up rules:
- One volunteer per day. Sign up on the Volunteer Calendar while logged in.
- First-time volunteers must choose a training day, from today through the \
day before their route, so a first-timer can't sign up for today's route.
- Volunteers can cancel upcoming routes from their dashboard.

Produce box rules:
- Logged-in users can reserve one box per farmstand while boxes are left, on \
the Farmstand page, and cancel there or on their dashboard. Pick it up at \
the farmstand."""


def schedule_text():
    lines = []
    for when, opportunities in volunteer.SCHEDULE_SUMMARY:
        for o in opportunities:
            kind = volunteer.KIND_LABELS.get(o.kind, o.kind)
            lines.append(f"- {when}, {o.time_label}: {o.title} ({kind}). {o.description}")
    return "\n".join(lines)


def this_week_text():
    """Today's date, the volunteer schedule, and the next farmstand's listing."""
    db = get_db()
    today = current_date()
    friday = farmstand.next_farmstand(today)
    items = db.execute(
        "SELECT name, note FROM harvest_items WHERE farmstand_date = %s ORDER BY id",
        (friday.isoformat(),),
    ).fetchall()
    note = db.execute(
        "SELECT note FROM farmstand_days WHERE farmstand_date = %s", (friday.isoformat(),)
    ).fetchone()
    boxes, reserved = farmstand.box_counts(db, friday)

    harvest = "\n".join(
        f"- {i['name']}" + (f" ({i['note']})" if i["note"] else "") for i in items
    ) or "- Not posted yet. The garden manager usually posts it by Friday morning."
    box_line = (f"{max(boxes - reserved, 0)} of {boxes} produce boxes left."
                if boxes else "No produce boxes offered yet.")
    return (
        f"Today is {volunteer.long_date(today)}.\n\n"
        f"Weekly volunteer schedule (drop-in: just show up; sign-up: log in and "
        f"claim it; event: no volunteers needed):\n{schedule_text()}\n\n"
        f"Next farmstand: {volunteer.long_date(friday)}, {volunteer.FARMSTAND.time_label}. "
        f"{volunteer.FARMSTAND.description}\n"
        f"Harvest listed for that day:\n{harvest}\n"
        f"{box_line}"
        + (f"\nNote from the garden manager: {note['note']}" if note and note["note"] else "")
    )


def conversation_id():
    if "chat_id" not in session:
        session["chat_id"] = uuid.uuid4().hex
    return session["chat_id"]


def load_messages(chat_id):
    return get_db().execute(
        "SELECT role, content FROM chat_messages WHERE conversation_id = %s ORDER BY id",
        (chat_id,),
    ).fetchall()


def messages_sent_today(username):
    return get_db().execute(
        "SELECT COUNT(*) AS n FROM chat_messages WHERE username = %s AND role = 'user'"
        f" AND left(created_at, 10) = {TODAY_TEXT}",
        (username,),
    ).fetchone()["n"]


def ask_claude(history):
    """Send the conversation to Claude. Returns the reply text, or None on failure."""
    try:
        response = plant_doctor.create_message(
            model=MODEL,
            max_tokens=2000,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT},
                {"type": "text", "text": this_week_text()},
            ],
            messages=[{"role": m["role"], "content": m["content"]} for m in history],
            output_config={"effort": "low"},
        )
    except plant_doctor.ai_errors():
        current_app.logger.warning("Garden Helper request failed", exc_info=True)
        return None
    if response.stop_reason == "refusal":
        return ("Sorry, I can't help with that. I can answer questions about the "
                "Forge Garden, volunteering, the farmstand, and organic gardening.")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    enabled = plant_doctor.is_enabled()
    username = session["username"]
    chat_id = conversation_id()
    used = messages_sent_today(username)

    if request.method == "POST" and enabled:
        message, err = clean(request.form, "message", "Your message", MAX_MESSAGE_CHARS)
        if err:
            flash(err, "error")
        elif used >= DAILY_LIMIT:
            flash(f"You've reached today's limit of {DAILY_LIMIT} messages. "
                  "Please come back tomorrow!", "error")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO chat_messages (conversation_id, username, role, content)"
                " VALUES (%s, %s, 'user', %s)", (chat_id, username, message),
            )
            db.commit()
            history = list(load_messages(chat_id)[-HISTORY_MESSAGES:])
            while history and history[0]["role"] != "user":  # must start with a user turn
                history.pop(0)
            reply = ask_claude(history)
            if reply is None:
                flash("The Garden Helper couldn't answer just now. Please try again.", "error")
            else:
                db.execute(
                    "INSERT INTO chat_messages (conversation_id, username, role, content)"
                    " VALUES (%s, %s, 'assistant', %s)", (chat_id, username, reply),
                )
                db.commit()
        return redirect(url_for("chat.index") + "#latest")

    return render_template(
        "chat.html",
        enabled=enabled,
        messages=load_messages(chat_id),
        suggestions=SUGGESTIONS,
        remaining=max(DAILY_LIMIT - used, 0),
        daily_limit=DAILY_LIMIT,
        max_chars=MAX_MESSAGE_CHARS,
        username=username,
    )


@bp.route("/new", methods=["POST"])
@login_required
def new_chat():
    session.pop("chat_id", None)
    return redirect(url_for("chat.index"))
