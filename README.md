# ForgeGarden

A Flask web app for Santa Clara University's Forge Garden. It has:

- An **About page** (the homepage) describing the garden and its program goals.
- **Accounts**: anyone can register with a username and password, then log in. Every page except About, Login, and Register requires login.
- A **Volunteer Calendar**: a week-by-week grid (9am–6pm) showing drop-in volunteer hours, sign-up shifts, and garden events.
- **Compost route sign-ups**, with a training day required the first time.
- **Plant Help**, a community question-and-answer board for plant problems like wilting or pests. Logged-in users can read, ask, and answer.
- A **Garden Journal**, a blog where the garden manager shares thoughts and readings about the garden and the environment.
- A **dashboard** where logged-in volunteers can see and cancel their upcoming sign-ups.

## Setup

Requires Python 3.10 or newer.

1. Create a virtual environment and install dependencies:

       python3 -m venv .venv
       .venv/bin/pip install -r requirements.txt

2. Create a `.env` file in the project root with these variables:

       SECRET_KEY=
       ADMIN_USERNAME=
       SITE_NAME=Forge Garden

   | Variable         | What it does                                                                             |
   | ---------------- | ---------------------------------------------------------------------------------------- |
   | `SECRET_KEY`     | Signs session cookies and CSRF tokens. **Required**: the app won't start without it.    |
   | `ADMIN_USERNAME` | The username of the admin / garden manager. Everyone else is `user`. **Required**: the app won't start without it. |
   | `SITE_NAME`      | Name shown in the page header. Defaults to `Forge Garden`.                               |

   Fill in `SECRET_KEY` and `ADMIN_USERNAME` yourself. One way to generate a secret key:

       .venv/bin/python -c "import secrets; print(secrets.token_hex(32))"

   `.env` is listed in `.gitignore`. Don't commit it.

   The admin is whoever has the `ADMIN_USERNAME` account, so register that username yourself right after setting up a new deployment.

## Running the app

    .venv/bin/flask --app app run --debug

Then open http://127.0.0.1:5000.

The app stores user accounts, compost route sign-ups, Plant Help posts, and journal posts in a SQLite database, `forge.db`, in the project folder. It's created automatically the first time it's needed, and any missing tables are added automatically, so an existing `forge.db` keeps working. It's ignored by git. Delete it to start over with no data.

## Accounts and security

- Register at `/register`. Usernames are 3–32 characters (letters, numbers, dots, dashes, underscores) and are not case-sensitive. Passwords need at least 8 characters.
- Only Werkzeug password hashes are stored in the `users` table, never the passwords themselves.
- The session cookie is `HttpOnly` and `SameSite=Lax`. It's also `Secure` when running on Cloud Run (when `K_SERVICE` is set).
- Every POST form includes a CSRF token (Flask-WTF `CSRFProtect`). Log out is a POST button on the dashboard.

## Pages

| Route                               | Login required | Description                                                         |
| ----------------------------------- | -------------- | ------------------------------------------------------------------- |
| `/`                                 | No             | About the Forge Garden. (`/about` redirects here.)                  |
| `/register`                         | No             | Create an account.                                                  |
| `/login`                            | No             | Login form.                                                         |
| `/calendar`                         | Yes            | Volunteer Calendar for the current week (Sunday–Saturday). `?week=2026-12-01` shows the week containing that date. |
| `/calendar/compost/<YYYY-MM-DD>`    | Yes            | Sign up to run the compost route on that day.                       |
| `/calendar/compost/<YYYY-MM-DD>/cancel` | Yes (POST) | Cancel your own upcoming sign-up.                                   |
| `/plant-help/`                      | Yes            | Plant Help board. `?topic=pests` filters by topic.                  |
| `/plant-help/ask`                   | Yes            | Ask a question.                                                     |
| `/plant-help/<id>`                  | Yes            | A question and its answers.                                         |
| `/journal/`                         | Yes            | Garden Journal. `?kind=thought` or `?kind=reading` filters by type.  |
| `/journal/<id>`                     | Yes            | A single journal post.                                              |
| `/journal/new`, `/journal/<id>/edit`| Admin only     | Write or edit a journal post.                                       |
| `/dashboard`                        | Yes            | Your username, role, and upcoming compost routes.                   |
| `/logout`                           | Yes (POST)     | Logs out and returns to the homepage.                               |

Logged-out visitors who open a login-required page are sent to `/login?next=<page>` and return there after logging in.

## Volunteer schedule

Each week is shown as a grid with one column per day and a 9am–6pm time axis. Blocks are sized by their start and end times. The compost route has only a start time, so it's drawn as a short 40-minute block. On phones, the grid becomes a list of the week's remaining days.

The calendar color-codes three kinds of opportunities:

- **Green: drop-in hours.** Just show up, no sign-up needed.
- **Purple: sign-up required.** Claim the shift.
- **Blue: garden events.** Shown for reference; no volunteers needed.

| When       | Opportunity        | Time            | Kind      | Notes                                                                 |
| ---------- | ------------------ | --------------- | --------- | --------------------------------------------------------------------- |
| Every day  | Compost Route      | 10:20am         | Sign-up   | One volunteer per day. First-timers must pick a training day.         |
| Mondays    | Nourish Night Prep | 4:30–6pm        | Drop-in   | Prep food for Nourish Night (free plant-based meal for students).     |
| Tuesdays   | Glean Team         | 1–2pm           | Drop-in   | Pick excess fruit from neighborhood trees, with owners' permission.   |
| Tuesdays   | Garden Work        | 2:30–4pm        | Drop-in   | Work around the garden.                                               |
| Fridays    | Farmstand Harvest  | 9:30–11:30am    | Drop-in   | Harvest what's ready for that day's farmstand.                        |
| Fridays    | Farmstand          | 11:30am–1:30pm  | Event     | 11:30–12:30 is student hour; 12:30–1:30 is open to everyone.          |

### Compost route sign-up rules

- Only one volunteer can sign up for each day's route.
- A volunteer with no previous sign-ups must choose a **training day**, from today through the day before the route. That means a first-timer can't sign up for today's route.
- Past dates can't be signed up for or cancelled.
- Volunteers can cancel their own upcoming routes from the dashboard.

### Changing the schedule

The weekly schedule lives in [`volunteer.py`](volunteer.py). The grid covers `GRID_START` to `GRID_END` (9am–6pm). Widen that range if you add anything earlier or later. To change a time or description, edit the matching `Opportunity`. To move an opportunity to a different day, change the `WEEKLY` dictionary, which is keyed by weekday (Monday = 0). Also update `SCHEDULE_SUMMARY` so the "Weekly schedule" section below the calendar matches.

## Plant Help board

- Questions have a topic: Wilting, Pests, Disease & Mold, Soil & Compost, Watering, or Other.
- The person who asked can mark one answer as **"This helped"** (click again to unmark).
- Answers from the garden manager show a **Garden Manager** badge.
- People can delete their own questions and answers. The garden manager can delete any post. Deleting a question deletes its answers.
- The board shows a reminder that the Forge Garden is CCOF-certified organic, so answers should suggest organic methods only.

## Garden Journal

- Only the garden manager (the `ADMIN_USERNAME` user) can write, edit, or delete posts. Every logged-in user can read them.
- Each post is a **Thought** or a **Reading**. A post can include an optional reading title and link (`http://` or `https://` only).
- The journal is meant for longer-form posts and is separate from any future announcements page.

Posts on both pages are plain text: any HTML is shown as text, not rendered. Leave a blank line between paragraphs.

## Project structure

    app.py              Flask app setup, settings, About/register/login/dashboard, calendar routes
    auth.py             Accounts, password checks, login_required / admin_required, roles
    db.py               SQLite connection and table definitions (including users)
    volunteer.py        Volunteer schedule data and calendar helpers
    board.py            Plant Help board routes
    journal.py          Garden Journal routes
    content.py          Text helpers: paragraphs, excerpts, dates, form checks
    templates/          Jinja templates (_header.html is the shared nav bar)
    static/style.css    Styles, including light and dark mode colors
    tests/              pytest tests
    requirements.txt    Pinned dependencies

## Running tests

    .venv/bin/pytest

Tests use a temporary database and a fixed "today" date (`TODAY` in the app config), so they don't touch `forge.db` and give the same results on any day. They use their own test `SECRET_KEY` and `ADMIN_USERNAME` (not `.env`), create test accounts in the temporary database, and turn CSRF off except in the tests that check it.
