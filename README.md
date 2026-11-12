# ForgeGarden

## Setup

1. Create a virtual environment and install dependencies:

       python3 -m venv .venv
       .venv/bin/pip install -r requirements.txt

2. Create a `.env` file in the project root with these variables:

       SECRET_KEY=
       ADMIN_USERNAME=
       SITE_NAME=Forge Garden

   Fill in `SECRET_KEY` and `ADMIN_USERNAME` yourself. Don't commit this file.

## Running tests

    .venv/bin/pytest