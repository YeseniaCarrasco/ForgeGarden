"""User accounts, login checks, and roles.

Accounts live in the users table (see db.py); only Werkzeug password hashes
are stored. The admin (set by ADMIN_USERNAME in the environment) is the
garden manager: they write Garden Journal posts and can remove any Plant Help
post. Everyone else is a user.
"""
import re
from functools import wraps

from flask import abort, current_app, flash, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import IntegrityError, get_db

USERNAME_MIN, USERNAME_MAX = 3, 32
PASSWORD_MIN = 8
USERNAME_CHARS = re.compile(r"^[a-z0-9_.-]+$")


def normalize_username(text):
    return (text or "").strip().lower()


def get_user(username):
    if not username:
        return None
    return get_db().execute(
        "SELECT id, username, password_hash, created_at FROM users WHERE username = %s",
        (username,),
    ).fetchone()


def validate_registration(username, password, confirm):
    """Return a list of error messages (empty if the form is OK)."""
    errors = []
    if not USERNAME_MIN <= len(username) <= USERNAME_MAX:
        errors.append(f"Username must be {USERNAME_MIN}-{USERNAME_MAX} characters.")
    elif not USERNAME_CHARS.match(username):
        errors.append("Username can use only letters, numbers, dots, dashes, and underscores.")
    if len(password) < PASSWORD_MIN:
        errors.append(f"Password must be at least {PASSWORD_MIN} characters.")
    elif password != confirm:
        errors.append("Passwords don't match.")
    return errors


def create_user(username, password):
    """Insert a user. Returns False if the username is already taken."""
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, generate_password_hash(password)),
        )
        db.commit()
    except IntegrityError:  # UNIQUE username
        db.rollback()
        return False
    return True


def check_login(username, password):
    """Return the user row if the username and password match, else None."""
    user = get_user(username)
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def role_for(username):
    return "admin" if username and username == current_app.config["ADMIN_USERNAME"] else "user"


def is_admin(username=None):
    return role_for(username if username is not None else session.get("username")) == "admin"


def redirect_to_login():
    flash("Please log in to continue.", "error")
    return redirect(url_for("login", next=request.path))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect_to_login()
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_admin():
            abort(403)
        return view(*args, **kwargs)

    return wrapped
