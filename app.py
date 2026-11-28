"""ForgeGarden - Flask app for the Forge Garden.

Pages: About, Volunteer Calendar (with compost route sign-ups), Plant Help
board (with photos and the AI Plant Doctor), Garden Journal, Friday Farmstand
(harvest list and produce box reservations), Garden Helper AI chat, register,
login, and dashboard. Anyone can view the About page, calendar, Plant Help,
journal, and farmstand; posting, signing up, reserving, chatting, and the
dashboard require login.
"""
import os
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, redirect, render_template, request, session, url_for,
)
from flask_wtf.csrf import CSRFProtect

import board
import chatbot
import content
import farmstand
import journal
import storage
import volunteer
from auth import (
    LOCKOUT_MINUTES, clear_failed_logins, is_locked_out, record_failed_login,
    check_login, create_user, get_user, is_admin, login_required, normalize_username,
    redirect_to_login, role_for, validate_registration,
)
from db import IntegrityError, close_db, current_date, get_db, init_db

load_dotenv()

csrf = CSRFProtect()

# Settings that must come from the environment (.env). There are no defaults.
REQUIRED_SETTINGS = ("SECRET_KEY", "ADMIN_USERNAME", "DATABASE_URL")

# Endpoints anyone can open without logging in. "static" serves the CSS.
PUBLIC_ENDPOINTS = {"about", "about_alias", "login", "register", "static"}

# Read-only pages anyone can view (GET only): Plant Help questions and answers,
# the volunteer calendar, and the farmstand. Everything else needs login,
# including the Garden Journal and the Garden Helper chat. Every route that
# changes data also has its own login_required / admin_required check.
# photos.serve is listed so it can decide per photo: Plant Help and farmstand
# photos are public, and every other photo (journal photos) needs login.
PUBLIC_VIEW_ENDPOINTS = {
    "volunteer_calendar",
    "board.index", "board.question",
    "farmstand.index",
    "photos.serve",
}


def parse_day(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        abort(404)


def safe_next_url():
    """The ?next= path, if it is a path on this site (avoids open redirects)."""
    return content.local_path(request.args.get("next", ""))


def create_app(test_config=None):
    app = Flask(__name__)
    for name in REQUIRED_SETTINGS:
        app.config[name] = os.environ.get(name, "")
    app.config["SITE_NAME"] = os.environ.get("SITE_NAME") or "Forge Garden"
    # Photos: a Google Cloud Storage bucket if GCS_BUCKET is set, else this local folder.
    app.config["GCS_BUCKET"] = os.environ.get("GCS_BUCKET", "").strip()
    app.config["UPLOAD_FOLDER"] = os.path.join(app.instance_path, "uploads")
    app.config["MAX_CONTENT_LENGTH"] = storage.MAX_PHOTO_BYTES + 1024 * 1024
    # Plant Doctor and Garden Helper (Claude API) are on only when this key is set.
    app.config["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    # Keep the session cookie away from JavaScript and cross-site form posts.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Cloud Run sets K_SERVICE and serves over HTTPS; local dev is plain HTTP.
    app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("K_SERVICE"))
    if test_config:
        app.config.update(test_config)

    for name in REQUIRED_SETTINGS:
        if not str(app.config.get(name) or "").strip():
            raise RuntimeError(
                f"{name} is not set. Add {name}=... to .env (or the environment) "
                "and start the app again."
            )
    app.config["ADMIN_USERNAME"] = normalize_username(app.config["ADMIN_USERNAME"])
    init_db(app.config["DATABASE_URL"])  # create any missing tables

    csrf.init_app(app)
    app.teardown_appcontext(close_db)
    app.add_template_filter(volunteer.long_date, "long_date")
    app.add_template_filter(content.paragraphs, "paragraphs")
    app.add_template_filter(content.short_date, "short_date")
    app.register_blueprint(board.bp)
    app.register_blueprint(journal.bp)
    app.register_blueprint(farmstand.bp)
    app.register_blueprint(storage.bp)
    app.register_blueprint(chatbot.bp)

    @app.errorhandler(413)
    def too_large(_error):
        flash("That upload is too big. Photos must be 5 MB or smaller.", "error")
        # Go back to the form the upload came from (same site only).
        referrer = request.referrer or ""
        if referrer.startswith(request.host_url):
            return redirect(referrer)
        return redirect(url_for("about"))

    @app.after_request
    def security_headers(response):
        """Browser protections for every page."""
        headers = response.headers
        # Don't let other sites show our pages in a frame (clickjacking).
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
        )
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if app.config["SESSION_COOKIE_SECURE"]:  # only when served over HTTPS (Cloud Run)
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.context_processor
    def inject_globals():
        return {
            "site_name": app.config["SITE_NAME"],
            "is_admin": is_admin,
        }

    @app.before_request
    def require_login():
        username = session.get("username")
        if username and get_user(username) is None:
            session.clear()  # the account no longer exists
        # endpoint is None for unknown URLs; let those 404 normally.
        if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if request.endpoint in PUBLIC_VIEW_ENDPOINTS and request.method in ("GET", "HEAD"):
            return None
        if "username" not in session:
            return redirect_to_login()
        return None

    @app.route("/")
    def about():
        return render_template("about.html")

    @app.route("/about")
    def about_alias():
        return redirect(url_for("about"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        errors, username = [], ""
        if request.method == "POST":
            username = normalize_username(request.form.get("username"))
            password = request.form.get("password", "")
            errors = validate_registration(username, password, request.form.get("confirm", ""))
            if not errors and not create_user(username, password):
                errors.append("That username is taken. Please choose another.")
            if not errors:
                session.clear()
                session["username"] = username
                flash(f"Welcome, {username}! Your account is ready.", "success")
                return redirect(safe_next_url() or url_for("dashboard"))
        return render_template(
            "register.html", errors=errors, username=username,
        ), (400 if errors else 200)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = normalize_username(request.form.get("username"))
            if is_locked_out(username):
                flash("Too many failed login attempts for this account. "
                      f"Please wait {LOCKOUT_MINUTES} minutes and try again.", "error")
                return render_template("login.html"), 429
            user = check_login(username, request.form.get("password", ""))
            if user:
                clear_failed_logins(username)
                session.clear()
                session["username"] = user["username"]
                flash(f"Welcome back, {user['username']}!", "success")
                return redirect(safe_next_url() or url_for("dashboard"))
            record_failed_login(username)
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/dashboard")
    @login_required
    def dashboard():
        username = session["username"]
        rows = get_db().execute(
            "SELECT route_date, training_date FROM compost_signups"
            " WHERE username = %s AND route_date >= %s ORDER BY route_date",
            (username, current_date().isoformat()),
        ).fetchall()
        boxes = [
            date.fromisoformat(r["farmstand_date"])
            for r in get_db().execute(
                "SELECT farmstand_date FROM box_reservations"
                " WHERE username = %s AND farmstand_date >= %s ORDER BY farmstand_date",
                (username, current_date().isoformat()),
            )
        ]
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
            role=role_for(username),
            signups=signups,
            boxes=boxes,
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
            " WHERE route_date BETWEEN %s AND %s",
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
            "SELECT username FROM compost_signups WHERE route_date = %s",
            (route_day.isoformat(),),
        ).fetchone()
        first_time = db.execute(
            "SELECT 1 FROM compost_signups WHERE username = %s LIMIT 1", (username,)
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
                        " VALUES (%s, %s, %s)",
                        (route_day.isoformat(), username,
                         training_day and training_day.isoformat()),
                    )
                    db.commit()
                except IntegrityError:  # UNIQUE route_date: someone else got it first
                    db.rollback()
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
                "DELETE FROM compost_signups WHERE route_date = %s AND username = %s",
                (route_day.isoformat(), session["username"]),
            ).rowcount
            db.commit()
            if deleted:
                flash(f"Cancelled your compost route on {volunteer.long_date(route_day)}.", "success")
            else:
                flash("You weren't signed up for that route.", "error")
        return redirect(url_for("dashboard"))

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("about"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run()
