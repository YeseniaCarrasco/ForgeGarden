# Security review

An AI-assisted security review of ForgeGarden, done on November 25, 2026, against the code on `main` plus the Cloud Run deploy files and GitHub Actions workflow (PR #11).

## How it was done

Claude Code (Claude Opus 5.5) worked through the app with a teammate:

1. **Read every source file**, template, and the GitHub Actions workflow, looking for the usual web-app problems: SQL injection, cross-site scripting (XSS), cross-site request forgery (CSRF), broken access checks, unsafe file uploads, open redirects, session handling, leaked secrets, and abuse of paid services.
2. **Searched the code** for risky patterns: SQL built from strings, HTML marked as safe (`|safe`, `Markup`), CSRF exemptions, redirects built from user input, and debug settings.
3. **Scanned the dependencies** in `requirements.txt` against the public vulnerability database with [`pip-audit`](https://pypi.org/project/pip-audit/).
4. **Searched the whole Git history** for committed secrets (Claude API keys, Neon passwords, Google service account keys). None were found.
5. **Confirmed each suspected problem** by trying it before fixing it, then added a test that would fail if it came back ([`tests/test_security.py`](tests/test_security.py)).

A person reviewed every finding and fix. An AI review is a good first pass, not a guarantee: it can miss problems, especially in how Google Cloud, Neon, and GitHub are configured, which it could only partly see.

## Summary

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| 1 | Open redirect after login | Medium | Fixed |
| 2 | No limit on password guessing | Medium | Fixed |
| 3 | AI usage could run up the API bill | Medium | Fixed |
| 4 | `cryptography` package had known vulnerabilities | Medium | Fixed |
| 5 | Pages could be framed by other sites (clickjacking) | Low | Fixed |
| 6 | The garden manager role belongs to whoever registers that username first | Low | Accepted, documented |
| 7 | Deploys use a long-lived Google service account key | Low | Recommendation |
| 8 | Failed-login lockout can be triggered by someone else | Low | Accepted trade-off |
| 9 | Prompt injection in the AI features | Info | Low impact, no change |
| 10 | Chat history is kept forever | Info | Recommendation |
| 11 | Secrets were shared in chat messages | Info | Recommendation |

## Findings

### 1. Open redirect after login (Medium, fixed)

After logging in, the app sends people to the page in `?next=`. The check only allowed values starting with `/` and not `//`, to stay on this site. But browsers remove tabs and newlines from addresses, so `?next=/%09/evil.example` passed the check and the browser then went to `https://evil.example`. Someone could send a real ForgeGarden login link that lands people on a look-alike site right after they log in. The farmstand "cancel" button had the same check.

**Fix:** a single check, `content.local_path`, now decides whether an address is on this site. It rejects `//`, backslashes, any whitespace or control characters, and anything with a scheme or host. Login, registration, and the farmstand cancel button all use it.

### 2. No limit on password guessing (Medium, fixed)

Nothing slowed down repeated login attempts, so a script could try many passwords for an account.

**Fix:** after 10 wrong passwords for one username within 15 minutes, that username can't log in until the older failures age out, and the login form answers with HTTP 429. Failures are stored in a new `failed_logins` table, so the limit works across all Cloud Run instances. A successful login clears them.

### 3. AI usage could run up the API bill (Medium, fixed)

Every new Plant Help question calls Claude (with a photo, if attached), with no limit. The Garden Helper had a per-user limit of 40 messages a day, but anyone can register any number of accounts, so neither feature had a real ceiling.

**Fix:** a daily limit of 10 Plant Doctor drafts per user, plus a site-wide limit of 500 AI requests a day across both features (Pacific time). Past a limit, questions still post without an AI draft and the chat asks people to come back tomorrow. The numbers are constants in [`plant_doctor.py`](plant_doctor.py) and [`chatbot.py`](chatbot.py). We also recommend setting a monthly spend limit on the API key's workspace in the Claude Console, as a backstop outside the app.

### 4. `cryptography` package had known vulnerabilities (Medium, fixed)

`pip-audit` reported 3 advisories for `cryptography` 48.0.1 (PYSEC-2026-3552, -3553, -3554), fixed in 49.0.0 and 50.0.0. It's installed as a dependency of the Google client libraries.

**Fix:** pinned `cryptography==50.0.2`. `pip-audit` now reports no known vulnerabilities, and `pip check` reports no conflicts.

### 5. Pages could be framed by other sites (Low, fixed)

The app sent no headers telling browsers not to show it inside another site's frame. A hostile page could load ForgeGarden invisibly and trick a logged-in user into clicking a button, such as cancelling a reservation (clickjacking).

**Fix:** every response now sends `X-Frame-Options: DENY`, a `Content-Security-Policy` with `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'` and `object-src 'none'`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: strict-origin-when-cross-origin`. On Cloud Run it also sends `Strict-Transport-Security`. The policy doesn't restrict scripts, because some pages use small inline scripts. Moving those into a file would allow a stricter policy later.

### 6. The garden manager role belongs to whoever registers that username first (Low, accepted)

The manager is "the account named `ADMIN_USERNAME`". On a brand-new deployment, if someone else registers that username before the team does, they become the manager.

**Status:** the live site's manager account is already registered, so this only matters for new deployments. The README tells whoever deploys to register the manager account right away. A stronger design would store roles in the database and assign them deliberately.

### 7. Deploys use a long-lived Google service account key (Low, recommendation)

GitHub Actions signs in to Google Cloud with a JSON key stored in the `GCP_CREDENTIALS` secret. The workflow handles it carefully (the file is readable only by the runner, then signed out and deleted, even on failure), but the key itself doesn't expire. If it leaked, it would work until someone deletes it.

**Recommendation:** switch to Workload Identity Federation (`google-github-actions/auth` with a workload identity provider), which gives each run short-lived credentials and removes the stored key. Until then, give the deploy account only the roles it needs and delete the key when the project ends.

### 8. Failed-login lockout can be triggered by someone else (Low, accepted trade-off)

Because the lockout from finding 2 is per username, someone who knows a username can enter wrong passwords to lock that person out for up to 15 minutes.

**Status:** accepted. A short lockout is a common trade-off, and it's much less harmful than unlimited guessing. Limiting by IP address as well would need the app to read Cloud Run's forwarded-address header safely, which is more involved.

### 9. Prompt injection in the AI features (Info, low impact)

Questions, photos, and chat messages go into Claude's prompts, so someone can write text meant to steer the AI ("ignore your instructions…").

**Why it's low impact:** the AI can't do anything. It has no tools, no database access, and no way to see other people's data, and its replies are shown as plain text with HTML escaped. Plant Help text is wrapped in `<question>` tags, and the prompt says to treat it as a description, not instructions. The Plant Doctor's reply must match a fixed JSON schema, and its topic must be one of six values. The worst case is an off-topic or wrong AI answer, which both features already label as AI-generated and possibly wrong.

### 10. Chat history is kept forever (Info, recommendation)

Garden Helper conversations stay in `chat_messages` indefinitely. Only the person who wrote them can see them in the app, but the team can see them in the database.

**Recommendation:** delete chats older than, say, 30 days, and mention on the chat page that conversations are saved.

### 11. Secrets were shared in chat messages (Info, recommendation)

During development, the Neon connection strings, Claude API keys, and the manager password were sent between teammates in chat messages. None of them are in the repository (checked across the full Git history), and production secrets live in Google Secret Manager.

**Recommendation:** when the class project ends, reset the Neon password, delete the Claude API keys, change the manager password, and delete the GitHub deploy key. In the future, share secrets through a password manager, not chat.

## What was checked and found OK

- **SQL injection:** every query uses parameters (`%s` with psycopg). The only SQL built with an f-string is the test-only `TRUNCATE`, which uses a fixed list of table names.
- **XSS:** Jinja escapes everything automatically, and no template uses `|safe` or `Markup`. User posts and AI replies are shown as plain text. Journal links must start with `http://` or `https://`, which blocks `javascript:` links.
- **CSRF:** Flask-WTF protects every POST, and a test checks that every form in every template includes the token. Logout is a POST.
- **Access control:** every page except About, Login, and Register requires login. Only the author or the garden manager can delete questions and answers, only the asker can mark an answer as helpful, only the manager can write journal posts or manage the farmstand, people can cancel only their own reservations and compost routes, and each chat is tied to the signed session cookie of the person who started it.
- **Passwords and sessions:** passwords are stored only as Werkzeug hashes. The session is cleared on login (preventing session fixation), and the cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` on Cloud Run. The app won't start without a `SECRET_KEY`.
- **Photo uploads:** files are checked by their contents (JPEG, PNG, GIF, or WebP only, so no SVG or HTML), limited to 5 MB, and saved under random names. Photos are served only to logged-in users, with `nosniff`, from a private bucket.
- **Farmstand reservations:** a row lock (`SELECT … FOR UPDATE`) stops two people from both taking the last box at the same moment.
- **Secrets:** production secrets come from Secret Manager. `.env` is ignored by Git and left out of Cloud Run uploads by `.gcloudignore`. No secrets were found anywhere in the Git history.
- **Tests:** they refuse to run against the production database, and they block any real request to the Claude API.
- **CI/CD:** the workflow has read-only repository permissions, deploys only from `main` after the tests pass, and pull requests from forks don't receive the secrets.
