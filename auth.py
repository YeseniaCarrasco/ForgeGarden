"""Sample users, login checks, and roles.

The admin (set by ADMIN_USERNAME in .env) is the garden manager: they write
Garden Journal posts and can remove any Plant Help post.
"""
from functools import wraps

from flask import abort, current_app, flash, redirect, request, session, url_for
from werkzeug.security import generate_password_hash

# Sample users for development. Passwords are hashed before use;
# the plain-text values are kept only so the login page can display them.
SAMPLE_USERS = {
    "alice": {"name": "Alice Anvil", "password": "password123"},
    "bob": {"name": "Bob Builder", "password": "builder456"},
    "carol": {"name": "Carol Gardener", "password": "garden789"},
}
USERS = {
    username: {
        "name": info["name"],
        "password_hash": generate_password_hash(info["password"]),
    }
    for username, info in SAMPLE_USERS.items()
}


def role_for(username):
    return "admin" if username and username == current_app.config["ADMIN_USERNAME"] else "user"


def is_admin(username=None):
    return role_for(username if username is not None else session.get("username")) == "admin"


def display_name(username):
    user = USERS.get(username)
    return user["name"] if user else username


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
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
