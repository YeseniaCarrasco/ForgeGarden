"""ForgeGarden - simple Flask login app with sample users."""
import os
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

# Sample users for development. Passwords are hashed before use;
# the plain-text values are kept only so the login page can display them.
# Which user is the admin is set by ADMIN_USERNAME in .env.
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


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def create_app(test_config=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "").strip().lower()
    app.config["SITE_NAME"] = os.environ.get("SITE_NAME") or "Forge Garden"
    if test_config:
        app.config.update(test_config)

    def role_for(username):
        return "admin" if username == app.config["ADMIN_USERNAME"] else "user"

    @app.context_processor
    def inject_site_name():
        return {"site_name": app.config["SITE_NAME"]}

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
        return render_template(
            "dashboard.html",
            username=username,
            user=USERS[username],
            role=role_for(username),
        )

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("about"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
