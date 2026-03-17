# Food Calorie Intake Tracker

A multi-user web app to log meals, track daily calorie intake, and hit your macro goals — backed by USDA FoodData Central and a local SQLite database.

---

## Features

- **Multi-user accounts** — register with a username and password; all data is scoped to your account.
- **Daily calorie goal** — set a personal target; a colour-coded progress bar shows where you stand (blue → amber at 80 % → red when over goal).
- **USDA food search** — look up any food by name, pick a result, enter servings, and macros are auto-scaled.
- **Macro tracking** — calories, protein, carbs, and fat recorded for every entry.
- **History & export** — browse past days, view per-day summaries, or download all entries as CSV.

---

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

---

## Quick start

### 1 — Install dependencies

```bash
pip install -r requirements.txt
```

### 2 — (Optional) Set environment variables

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Flask session signing key | `dev-secret-change-in-production` |
| `USDA_FDC_API_KEY` | FoodData Central API key for food search | *(search disabled without it)* |

```bash
export SECRET_KEY="a-long-random-string"
export USDA_FDC_API_KEY="your-api-key-here"
```

Get a free USDA API key at <https://fdc.nal.usda.gov/api-key-signup.html>.

### 3 — Start the server

```bash
python web_app.py
```

Open `http://127.0.0.1:5000/` in your browser.

---

## Register & log in

1. Go to `/register` (redirected automatically if not logged in).
2. Choose a **username** and a **password** (minimum 6 characters); confirm the password.
3. Submit — you are logged in immediately and taken to today's dashboard.
4. On subsequent visits, use `/login` with your credentials.
5. Click **"Log out"** in the nav bar to end your session.

Each user's entries, settings, and calorie goal are fully isolated from other accounts.

---

## Using the app

| Page | What you can do |
|---|---|
| **Today** (`/`) | See today's entries and calorie total vs. goal; quick-add a food by name + calories |
| **Search USDA** (`/foods/search`) | Search FoodData Central by name |
| **Log food** (`/foods/log?food_id=…`) | Set servings & meal type; macros scale automatically |
| **History** (`/history`) | Per-day calorie totals for recent days |
| **Day view** (`/day/YYYY-MM-DD`) | All entries for a specific date |
| **All entries** (`/entries`) | Full log; download as CSV via `/export.csv` |
| **Settings** (`/settings`) | Set your daily calorie goal |

---

## Running tests

```bash
python -m pytest
```

The suite has **106 tests** across three files:

| File | Coverage |
|---|---|
| `tests/test_main.py` | DB layer — users, entries, foods, settings, calorie goal |
| `tests/test_usda_api.py` | USDA API client — macro extraction, search, error handling |
| `tests/test_web_app.py` | All Flask routes — auth, CRUD, isolation, CSV export |

All tests use an in-memory SQLite database and never touch `calories.db`.

---

## Project structure

```
food_calorie_intake/
├── main.py          # SQLite DB layer + dataclasses
├── web_app.py       # Flask app + all routes
├── usda_api.py      # USDA FoodData Central client
├── requirements.txt
├── pytest.ini
├── templates/       # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── settings.html
│   ├── search.html
│   ├── log_food.html
│   ├── history.html
│   ├── day.html
│   └── entries.html
└── tests/
    ├── test_main.py
    ├── test_usda_api.py
    └── test_web_app.py
```

