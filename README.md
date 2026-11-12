# ForgeGarden

A small Flask app with a login page, a dashboard, and a set of sample users for development.

## Setup

1. Create a virtual environment and install dependencies:

       python3 -m venv .venv
       .venv/bin/pip install -r requirements.txt

2. Create a `.env` file in the project root with these variables:

       SECRET_KEY=
       ADMIN_USERNAME=
       SITE_NAME=Forge Garden

   | Variable         | What it does                                                                 |
   | ---------------- | ---------------------------------------------------------------------------- |
   | `SECRET_KEY`     | Signs session cookies. If empty, the app falls back to an insecure dev-only key. |
   | `ADMIN_USERNAME` | Which sample user gets the `admin` role (for example `alice`). Everyone else is `user`. |
   | `SITE_NAME`      | Name shown in the page header. Defaults to `Forge Garden`.                    |

   Fill in `SECRET_KEY` and `ADMIN_USERNAME` yourself. Don't commit this file.

## Running the app

    .venv/bin/flask --app app run --debug

Then open http://127.0.0.1:5000.

## Sample users

These accounts exist for development only. Their passwords are also shown on the login page.

| Username | Name           | Password      |
| -------- | -------------- | ------------- |
| `alice`  | Alice Anvil    | `password123` |
| `bob`    | Bob Builder    | `builder456`  |
| `carol`  | Carol Gardener | `garden789`   |

## Pages

| Route        | Description                                                  |
| ------------ | ------------------------------------------------------------ |
| `/`          | Redirects to the dashboard if logged in, otherwise to login. |
| `/login`     | Login form.                                                  |
| `/dashboard` | Shows the logged-in user's name and role. Requires login.    |
| `/logout`    | Logs out and returns to the login page.                      |

## Running tests

    .venv/bin/pytest
