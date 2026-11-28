# ForgeGarden

A Flask web app for Santa Clara University's Forge Garden.

**Live site:** https://forge-garden-1028271237269.us-west1.run.app

It has:

- An **About page** (the homepage) describing the garden and its program goals.
- **Accounts**: anyone can register with a username and password, then log in. Anyone can view the About page, calendar, Plant Help, and farmstand; the Garden Journal, the Garden Helper chat, the dashboard, and every action (posting, signing up, reserving a box, managing) require login.
- A **Volunteer Calendar**: a week-by-week grid (9am–6pm) showing drop-in volunteer hours, sign-up shifts, and garden events.
- **Compost route sign-ups**, with a training day required the first time.
- **Plant Help**, a community question-and-answer board for plant problems like wilting or pests, with an optional photo on each question.
- The **Plant Doctor**, an AI (Claude) that writes a first take on each new Plant Help question: a suggested topic, likely causes, and an organic treatment idea.
- The **Garden Helper**, an AI chatbot (Claude) that answers questions about volunteering, the farmstand, the garden, and organic growing.
- A **Garden Journal**, a blog where the garden manager shares thoughts and readings, with optional photos.
- A **Friday Farmstand** page showing what's freshly harvested each week (with photos), where users can reserve a produce box.
- A **dashboard** where users can see and cancel their compost routes and produce boxes.

Built with Flask, PostgreSQL on Neon, the Claude API, and Google Cloud Run (with Cloud Storage for photos and Secret Manager for secrets). Every merge to `main` is tested and deployed automatically by GitHub Actions.

## Setup

Requires Python 3.10 or newer (the live site uses 3.13).

1. Create a virtual environment and install dependencies:

       python3 -m venv .venv
       .venv/bin/pip install -r requirements.txt

   On Windows, use `python -m venv .venv` and `.venv\Scripts\pip install -r requirements.txt`, and write `.venv\Scripts\` instead of `.venv/bin/` in the commands below.

   On an Intel Mac, `pip install -r requirements.txt` fails: cryptography 49 and later has no prebuilt package for Intel Macs. For local development only, install everything else plus cryptography 48.0.1:

       grep -v '^cryptography' requirements.txt > /tmp/req-mac.txt
       .venv/bin/pip install -r /tmp/req-mac.txt cryptography==48.0.1

   The live site and the GitHub tests still use the version pinned in `requirements.txt`.

2. Create a `.env` file in the project root with these variables:

       SECRET_KEY=
       ADMIN_USERNAME=
       DATABASE_URL=
       TEST_DATABASE_URL=
       SITE_NAME=Forge Garden
       ANTHROPIC_API_KEY=
       GCS_BUCKET=

   | Variable         | What it does                                                                             |
   | ---------------- | ---------------------------------------------------------------------------------------- |
   | `SECRET_KEY`     | Signs session cookies and CSRF tokens. **Required**: the app won't start without it.    |
   | `ADMIN_USERNAME` | The username of the admin / garden manager. Everyone else is `user`. **Required**: the app won't start without it. |
   | `DATABASE_URL`   | PostgreSQL connection string for the app's data (a Neon database, for example `postgresql://user:password@ep-….neon.tech/neondb?sslmode=require`). **Required**: the app won't start without it. |
   | `TEST_DATABASE_URL` | A **separate** PostgreSQL database used only by the tests. Tests empty every table, so never point this at real data. Tests refuse to run if it's missing or is the same database as `DATABASE_URL`. |
   | `SITE_NAME`      | Name shown in the page header. Defaults to `Forge Garden`.                               |
   | `ANTHROPIC_API_KEY` | Optional. Claude API key. Turns on the Plant Doctor and the Garden Helper chat. Leave empty to turn them off. See [AI setup](#ai-setup-claude-api). |
   | `GCS_BUCKET`     | Optional. Name of a Google Cloud Storage bucket for photos. Leave empty to store photos in `instance/uploads/` instead. |

   Fill in `SECRET_KEY`, `ADMIN_USERNAME`, and `DATABASE_URL` yourself. On Neon, create a second database (or branch) for `TEST_DATABASE_URL`. One way to generate a secret key:

       .venv/bin/python -c "import secrets; print(secrets.token_hex(32))"

   `.env` is listed in `.gitignore`. Don't commit it.

   The admin is whoever has the `ADMIN_USERNAME` account, so register that username yourself right after setting up a new deployment.

## Running the app

    .venv/bin/flask --app app run --debug

Then open http://127.0.0.1:5000.

Uploaded photos are saved in `instance/uploads/` (ignored by git) unless `GCS_BUCKET` is set; see [Photos](#photos).

The app stores accounts, compost route sign-ups, Plant Help posts, journal posts, farmstand data, and Garden Helper chats in the PostgreSQL database at `DATABASE_URL` (using psycopg). Any missing tables are created when the app starts. The old SQLite file, `forge.db`, is no longer used.

## Accounts and security

- Register at `/register`. Usernames are 3–32 characters (letters, numbers, dots, dashes, underscores) and are not case-sensitive. Passwords need at least 8 characters.
- Only Werkzeug password hashes are stored in the `users` table, never the passwords themselves.
- The session cookie is `HttpOnly` and `SameSite=Lax`. It's also `Secure` when running on Cloud Run (when `K_SERVICE` is set).
- Every POST form includes a CSRF token (Flask-WTF `CSRFProtect`). Log out is a POST button on the dashboard.
- After 10 wrong passwords for one username within 15 minutes, that username can't log in until the older failures are 15 minutes old (`MAX_FAILED_LOGINS` and `LOCKOUT_MINUTES` in [`auth.py`](auth.py)). Failures are stored in the `failed_logins` table, so the limit works across every Cloud Run instance.
- Redirect targets from requests (`?next=` after login, and the farmstand cancel button) must be a path on this site. `content.local_path` rejects other sites, including tricks like `/\evil.example` and `/<tab>/evil.example`.
- Every response sends browser security headers: `X-Frame-Options: DENY` and a `Content-Security-Policy` with `frame-ancestors 'none'` (no framing by other sites), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Strict-Transport-Security` on Cloud Run.
- Posts, answers, journal entries, and AI replies are shown as plain text (Jinja escapes any HTML). Database queries always use parameters, never text pasted into SQL.

See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the AI-assisted security review: what was checked, what was fixed, and the risks that remain.

## Pages

| Route                               | Login required | Description                                                         |
| ----------------------------------- | -------------- | ------------------------------------------------------------------- |
| `/`                                 | No             | About the Forge Garden. (`/about` redirects here.)                  |
| `/register`                         | No             | Create an account.                                                  |
| `/login`                            | No             | Login form.                                                         |
| `/calendar`                         | No (view only) | Volunteer Calendar for the current week (Sunday–Saturday). `?week=2026-12-01` shows the week containing that date. |
| `/calendar/compost/<YYYY-MM-DD>`    | Yes            | Sign up to run the compost route on that day.                       |
| `/calendar/compost/<YYYY-MM-DD>/cancel` | Yes (POST) | Cancel your own upcoming sign-up.                                   |
| `/plant-help/`                      | No (view only) | Plant Help board. `?topic=pests` filters by topic.                  |
| `/plant-help/ask`                   | Yes            | Ask a question.                                                     |
| `/plant-help/<id>`                  | No (view only) | A question and its answers.                                         |
| `/plant-help/<id>/answer`, `/helpful/<answer id>`, `/delete`, `/plant-help/answers/<id>/delete` | Yes (POST) | Answer, mark an answer as helpful (asker only), or delete (author or garden manager). |
| `/journal/`                         | Yes            | Garden Journal. `?kind=thought` or `?kind=reading` filters by type.  |
| `/journal/<id>`                     | Yes            | A single journal post.                                              |
| `/journal/new`, `/journal/<id>/edit`, `/journal/<id>/delete` | Admin only | Write, edit, or delete a journal post.                 |
| `/farmstand/`                       | No (view only) | This week's farmstand: harvest list and produce boxes. `?day=2026-12-01` shows the farmstand in that date's week. |
| `/farmstand/<YYYY-MM-DD>/reserve`, `/cancel` | Yes (POST) | Reserve or cancel your produce box for that Friday.          |
| `/farmstand/<YYYY-MM-DD>/items`, `/settings`, `/farmstand/items/<id>/delete` | Admin only (POST) | Add or remove harvest items; set the number of boxes and a note. |
| `/photos/<key>`                     | Depends        | An uploaded photo. Photos on Plant Help questions and farmstand items are public; journal photos need login. |
| `/garden-helper/`                   | Yes            | Garden Helper AI chat. POST `/garden-helper/new` starts a new chat. |
| `/dashboard`                        | Yes            | Your username, role, upcoming compost routes, and produce boxes.    |
| `/logout`                           | Yes (POST)     | Logs out and returns to the homepage.                               |

Logged-out visitors can only view the About page, the calendar, Plant Help questions and answers, and the farmstand. Opening any other page, or trying any action, sends them to `/login?next=<page>`, and they return there after logging in.

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

### Plant Doctor (AI)

When `ANTHROPIC_API_KEY` is set, each new question is sent (with its photo, if any) to Claude (`claude-sonnet-5-5`), which returns:

- a **suggested topic**. If the asker picks "Not sure", the question is filed under this topic,
- 1–4 **likely issues**, and
- an **organic treatment idea** that only uses CCOF-allowed methods.

This shows on the question page in a box clearly labeled as an AI draft, above the community answers. It runs while the question is being posted, so posting takes up to about a minute. If the AI is off, the form says the Plant Doctor isn't available right now. If the AI is off or the call fails, the question is posted normally without a draft ("Not sure" questions go under Other). The prompt is in [`plant_doctor.py`](plant_doctor.py). Each question costs a few cents, billed to the Claude API account that owns the key.

## Garden Helper (AI chat)

A chatbot for logged-in users at `/garden-helper/`, linked in the header and dashboard. It uses Claude (`claude-sonnet-5-5`) and answers from real site data: every request includes the garden's facts, the weekly volunteer schedule, today's date, and the next farmstand's harvest list, box count, and note. It's told to answer only garden-related questions, use organic methods only, keep replies short, and say so rather than guess when it doesn't know something.

- Conversations are saved in the `chat_messages` table. Each browser session has its own chat, and only that user can see it. **New chat** starts over.
- Claude sees the last 20 messages of the conversation.
- Each user can send 40 messages a day (`DAILY_LIMIT` in [`chatbot.py`](chatbot.py)) to keep API costs predictable. The count resets at midnight Pacific time. Each message costs a fraction of a cent to a few cents.
- It also stops for everyone once the site reaches its daily AI limit (see [AI spending limits](#ai-spending-limits)).
- The prompt and garden facts are in [`chatbot.py`](chatbot.py). Update them there if the garden's details change.

## AI setup (Claude API)

The Plant Doctor and Garden Helper call the Claude API (Claude Sonnet 5.5, `claude-sonnet-5-5`) with an API key. Usage is billed to the Claude API account that owns the key.

1. Create an API key in the [Claude Console](https://platform.claude.com/).
2. Set `ANTHROPIC_API_KEY=...` in `.env` (on Cloud Run, set it as a secret environment variable) and restart the app.

### AI spending limits

So one person, or many throwaway accounts, can't use up the API credits (days are Pacific time):

| Limit | Default | Where |
| --- | --- | --- |
| Plant Doctor drafts per user per day | 10 | `PLANT_DOCTOR_DAILY_LIMIT` in [`plant_doctor.py`](plant_doctor.py) |
| Garden Helper messages per user per day | 40 | `DAILY_LIMIT` in [`chatbot.py`](chatbot.py) |
| AI requests per day for the whole site (questions + chat messages) | 500 | `SITE_DAILY_LIMIT` in [`plant_doctor.py`](plant_doctor.py) |

Past a limit, questions still post (without an AI draft) and the chat shows a "come back tomorrow" message. It's also worth setting a monthly spend limit for the key's workspace in the Claude Console.

### Refusals and errors

If a safety check declines a request, the API can retry it on another model in the same call (server-side fallback, `fallbacks: "default"`). For Claude Sonnet 5.5 it retries "cyber" and "frontier_llm" declines on Claude Sonnet 5. Other declines aren't retried: the Plant Doctor then skips its draft, and the Garden Helper replies that it can't help with that. Requests time out after 60 seconds and are retried once.

Without a key, both features show a "not available right now" message. If a call fails for any reason (bad key, rate limit, timeout, network), the app keeps working: questions post without an AI draft, and the chat shows a "couldn't answer just now, please try again" message.

## Garden Journal

- Only the garden manager (the `ADMIN_USERNAME` user) can write, edit, or delete posts. Every logged-in user can read them.
- Each post is a **Thought** or a **Reading**. A post can include an optional reading title and link (`http://` or `https://` only).
- The journal is meant for longer-form posts and is separate from any future announcements page.

The garden manager can attach one photo to a post, and replace or remove it when editing.

## Friday Farmstand

- The page shows the next farmstand (the coming Friday). Use the arrows to see other weeks.
- The garden manager adds each harvested item (name, optional details like price, optional photo), sets how many produce boxes are available, and can add a note for the day. The manager also sees the list of who reserved a box.
- Logged-in users can reserve one box per farmstand while boxes are left, and cancel from the page or their dashboard. Past farmstands can't be reserved or cancelled.
- The manager can't set the box count below the number already reserved.

## Photos

Plant Help questions, journal posts, and harvest items can each have one photo (JPEG, PNG, GIF, or WebP, up to 5 MB). Files are checked by their contents and saved under a random name. They're served through `/photos/<key>`, so the bucket doesn't need to be public.

To store photos in Google Cloud Storage instead of on disk (needed on Cloud Run, where the disk is wiped on restart):

    gcloud storage buckets create gs://YOUR-BUCKET --location=us-west1 --uniform-bucket-level-access

Then set `GCS_BUCKET=YOUR-BUCKET`. The app uses Google's default credentials: on Cloud Run, give the service's service account the **Storage Object User** role on the bucket; locally, run `gcloud auth application-default login`.

Posts on both pages are plain text: any HTML is shown as text, not rendered. Leave a blank line between paragraphs.

## Deploying to Cloud Run

The app runs on Google Cloud Run as the service `forge-garden` (project `my-signup31`, region `us-west1`). `gcloud run deploy --source .` builds it from source with Google's buildpacks:

- [`Procfile`](Procfile) starts the app with gunicorn: `gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app`.
- [`.python-version`](.python-version) asks for Python 3.13, the version the pinned requirements are checked against.
- [`.gcloudignore`](.gcloudignore) keeps `.env`, `.venv/`, `forge.db`, `instance/`, the tests, and Git files out of the upload. Secrets come from Secret Manager, never from `.env`.

### Settings on Cloud Run

| Variable | Where it comes from |
| --- | --- |
| `SECRET_KEY` | Secret Manager secret `FORGE_SECRET_KEY` (latest version) |
| `DATABASE_URL` | Secret Manager secret `FORGE_DATABASE_URL` (the production Neon database) |
| `ANTHROPIC_API_KEY` | Secret Manager secret `FORGE_ANTHROPIC_API_KEY` |
| `ADMIN_USERNAME` | Plain environment variable (the garden manager's username) |
| `SITE_NAME` | Plain environment variable: `Forge Garden` |
| `TZ` | Plain environment variable: `America/Los_Angeles` |
| `GCS_BUCKET` | Plain environment variable: `forge-garden-photos-my-signup31` |

Deploys use `--update-secrets` and `--update-env-vars`, so they change only these settings and keep anything else already set on the service. The service's runtime service account needs **Secret Manager Secret Accessor** on the three secrets and **Storage Object User** on the photo bucket.

### Automatic deploys (GitHub Actions)

[`.github/workflows/tests.yml`](.github/workflows/tests.yml) has two jobs:

- **test** runs on every pull request and every push to `main`: Python 3.13, `pip install -r requirements.txt`, then `pytest`. It uses only the test database (`TEST_DATABASE_URL`) and no real keys. Test runs share a concurrency group, so two runs never use the test database at the same time; a new run waits for the current one to finish.
- **deploy** runs after **test** passes, only on a push to `main`. It signs in to Google Cloud with a service account key, runs `gcloud run deploy`, then signs out and deletes the key file, even if a step failed.

Set these once in the GitHub repository (**Settings → Secrets and variables → Actions**):

| Name | Kind | Value |
| --- | --- | --- |
| `TEST_DATABASE_URL` | Secret | Connection string for the separate **test** database. Never the production one: tests empty every table. |
| `GCP_CREDENTIALS` | Secret | JSON key for a deploy service account allowed to deploy from source (for example **Cloud Run Source Developer**, **Service Account User** and **Service Usage Consumer**). |
| `ADMIN_USERNAME` | Variable | The garden manager's username. The deploy job stops if it's missing. |

Pull requests from forks don't get these secrets, so their test job can't reach the test database.

### Deploying by hand

From the project folder, signed in with `gcloud auth login`:

    gcloud run deploy forge-garden --source . --project my-signup31 --region us-west1 \
      --update-secrets="SECRET_KEY=FORGE_SECRET_KEY:latest,DATABASE_URL=FORGE_DATABASE_URL:latest,ANTHROPIC_API_KEY=FORGE_ANTHROPIC_API_KEY:latest" \
      --update-env-vars="ADMIN_USERNAME=YOUR_ADMIN_USERNAME,SITE_NAME=Forge Garden,TZ=America/Los_Angeles,GCS_BUCKET=forge-garden-photos-my-signup31"

Replace `YOUR_ADMIN_USERNAME` with the garden manager's username. After the first deploy, register that username on the live site right away (see [Setup](#setup)).

## Project structure

    app.py              Flask app setup, settings, About/register/login/dashboard, calendar routes
    auth.py             Accounts, password checks, login_required / admin_required, roles
    db.py               PostgreSQL connection (psycopg) and table definitions
    volunteer.py        Volunteer schedule data and calendar helpers
    board.py            Plant Help board routes
    journal.py          Garden Journal routes
    farmstand.py        Friday Farmstand: harvest list and produce box reservations
    storage.py          Photo uploads (local folder or Google Cloud Storage)
    plant_doctor.py     Plant Doctor AI (Claude) for Plant Help questions
    chatbot.py          Garden Helper AI chat
    content.py          Text helpers: paragraphs, excerpts, dates, form checks
    templates/          Jinja templates (_header.html is the shared nav bar)
    static/style.css    Styles, including light and dark mode colors
    tests/              pytest tests
    requirements.txt    Pinned dependencies
    SECURITY_REVIEW.md  AI-assisted security review: findings, fixes, remaining risks
    Procfile            How Cloud Run starts the app (gunicorn)
    .python-version     Python version for the Cloud Run build
    .gcloudignore       Files left out of Cloud Run uploads
    .github/workflows/  GitHub Actions: tests on every PR, deploy on push to main

## Running tests

    .venv/bin/pytest

Tests never call the real Claude API or Google Cloud. The Plant Doctor and Garden Helper tests use a fake client, `ANTHROPIC_API_KEY` from `.env` is ignored, and any request a real Claude client tries to send is blocked before it leaves the machine.

Tests use the PostgreSQL database in `TEST_DATABASE_URL`, never `DATABASE_URL`. They stop before running anything if `TEST_DATABASE_URL` is missing or points at the same database as `DATABASE_URL` (Neon's pooled and direct hosts for one database count as the same). Every table is emptied before each test.

The full suite takes about 10 minutes against Neon, because every test empties the test database first. To run one file, name it, for example `.venv/bin/pytest tests/test_security.py`.

Tests also use a temporary photo folder and a fixed "today" date (`TODAY` in the app config), so they give the same results on any day. They use their own test `SECRET_KEY` and `ADMIN_USERNAME` (not the ones in `.env`), create test accounts in the test database, and turn CSRF off except in the tests that check it.
