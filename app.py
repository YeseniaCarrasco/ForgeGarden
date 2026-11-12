"""ForgeGarden - Flask app for the Forge Garden.

Pages: About, Volunteer Calendar (with compost route sign-ups), Plant Help
board, Garden Journal, login, and dashboard.
"""
import os
import sqlite3
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash

import board
import content
import journal
import volunteer
from auth import SAMPLE_USERS, USERS, display_name, is_admin, login_required, role_for
from db import close_db, current_date, get_db

load_dotenv()


def parse_day(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        abort(404)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "").strip().lower()
    app.config["SITE_NAME"] = os.environ.get("SITE_NAME") or "Forge Garden"
    app.config["DATABASE"] = os.path.join(app.root_path, "forge.db")
    # Don't send the session cookie on cross-site form posts.
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)
    app.add_template_filter(volunteer.long_date, "long_date")
    app.add_template_filter(content.paragraphs, "paragraphs")
    app.add_template_filter(content.short_date, "short_date")
    app.register_blueprint(board.bp)
    app.register_blueprint(journal.bp)

    @app.context_processor
    def inject_globals():
        return {
            "site_name": app.config["SITE_NAME"],
            "display_name": display_name,
            "is_admin": is_admin,
        }

    @app.route("/")
    def about():
        return render_template("about.html")

    @app.route("/about")
    def about_alias():
        return redirect(url_for("about"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            user = USERS.get(username)
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["username"] = username
                flash(f"Welcome back, {user['name']}!", "success")
                next_url = request.args.get("next", "")
                # Only allow local paths to avoid open redirects.
                if next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "error")
        samples = {u: {**info, "role": role_for(u)} for u, info in SAMPLE_USERS.items()}
        return render_template("login.html", sample_users=samples)

    @app.route("/dashboard")
    @login_required
    def dashboard():
        username = session["username"]
        rows = get_db().execute(
            "SELECT route_date, training_date FROM compost_signups"
            " WHERE username = ? AND route_date >= ? ORDER BY route_date",
            (username, current_date().isoformat()),
        ).fetchall()
        signups = [
            {
                "route_date": date.fromisoformat(r["route_date"]),
                "training_date": r["training_date"] and date.fromisoformat(r["training_date"]),
            }
            for r in rows
        ]
        return render_template(
            "dashboard.html",
            username=username,
            user=USERS[username],
            role=role_for(username),
            signups=signups,
            compost=volunteer.COMPOST_ROUTE,
        )

    @app.route("/calendar")
    def volunteer_calendar():
        today = current_date()
        try:
            anchor = date.fromisoformat(request.args.get("week", ""))
        except ValueError:
            anchor = today
        start = volunteer.week_start(anchor)
        dates = [start + timedelta(days=i) for i in range(7)]
        rows = get_db().execute(
            "SELECT route_date, username FROM compost_signups"
            " WHERE route_date BETWEEN ? AND ?",
            (dates[0].isoformat(), dates[-1].isoformat()),
        ).fetchall()
        days = []
        for d in dates:
            blocks, columns = volunteer.layout_day(d)
            days.append({"date": d, "blocks": blocks, "columns": columns})
        return render_template(
            "calendar.html",
            today=today,
            days=days,
            week_label=volunteer.week_label(start),
            hours=volunteer.hour_labels(),
            grid_rows=volunteer.GRID_ROWS,
            signups={r["route_date"]: r["username"] for r in rows},
            kind_labels=volunteer.KIND_LABELS,
            summary=volunteer.SCHEDULE_SUMMARY,
            prev_week=(start - timedelta(days=7)).isoformat(),
            next_week=(start + timedelta(days=7)).isoformat(),
            is_current_week=start == volunteer.week_start(today),
        )

    @app.route("/calendar/compost/<day>", methods=["GET", "POST"])
    @login_required
    def compost_signup(day):
        route_day = parse_day(day)
        today = current_date()
        username = session["username"]
        db = get_db()
        taken = db.execute(
            "SELECT username FROM compost_signups WHERE route_date = ?",
            (route_day.isoformat(),),
        ).fetchone()
        first_time = db.execute(
            "SELECT 1 FROM compost_signups WHERE username = ? LIMIT 1", (username,)
        ).fetchone() is None
        latest_training = route_day - timedelta(days=1)

        closed_reason = None
        if taken and taken["username"] == username:
            closed_reason = "You're already signed up for this route."
        elif taken:
            closed_reason = "Another volunteer has already signed up for this route."
        elif route_day < today:
            closed_reason = "This date has already passed."
        elif first_time and latest_training < today:
            closed_reason = (
                "First-time volunteers need a training day before their route. "
                "Please pick a later route date."
            )

        error = None
        if request.method == "POST":
            if closed_reason:
                flash(closed_reason, "error")
                return redirect(url_for("volunteer_calendar", week=route_day.isoformat()))
            training_day = None
            if first_time:
                try:
                    training_day = date.fromisoformat(request.form.get("training_date", ""))
                except ValueError:
                    error = "Please choose a training day."
                else:
                    if not today <= training_day <= latest_training:
                        error = "Your training day must be between today and the day before your route."
            if not error:
                try:
                    db.execute(
                        "INSERT INTO compost_signups (route_date, username, training_date)"
                        " VALUES (?, ?, ?)",
                        (route_day.isoformat(), username,
                         training_day and training_day.isoformat()),
                    )
                    db.commit()
                except sqlite3.IntegrityError:
                    error = "Someone just signed up for this route. Please pick another day."
                else:
                    flash(
                        f"You're signed up for the compost route on {volunteer.long_date(route_day)}.",
                        "success",
                    )
                    return redirect(url_for("volunteer_calendar", week=route_day.isoformat()))

        return render_template(
            "compost_signup.html",
            route_day=route_day,
            compost=volunteer.COMPOST_ROUTE,
            first_time=first_time,
            closed_reason=closed_reason,
            error=error,
            min_training=today,
            max_training=latest_training,
        ), (400 if error else 200)

    @app.route("/calendar/compost/<day>/cancel", methods=["POST"])
    @login_required
    def compost_cancel(day):
        route_day = parse_day(day)
        if route_day < current_date():
            flash("Past sign-ups can't be cancelled.", "error")
        else:
            db = get_db()
            deleted = db.execute(
                "DELETE FROM compost_signups WHERE route_date = ? AND username = ?",
                (route_day.isoformat(), session["username"]),
            ).rowcount
            db.commit()
            if deleted:
                flash(f"Cancelled your compost route on {volunteer.long_date(route_day)}.", "success")
            else:
                flash("You weren't signed up for that route.", "error")
        return redirect(url_for("dashboard"))

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("about"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
