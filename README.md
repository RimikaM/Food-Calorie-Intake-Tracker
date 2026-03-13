## Food Calorie Intake Tracker (Python CLI + Web)

Simple terminal app to log what you eat and track daily calories using a tiny SQLite database.

### Requirements

- Python 3.10+ (comes with `sqlite3` in the standard library)
- Flask + Requests (installed via `pip install -r requirements.txt`)

### How to run – CLI version

1. Open a terminal in this folder.
2. Run:

```bash
python main.py
```

The app will create a `calories.db` file in the same folder the first time it runs.

### How to run – Web version

1. (First time) install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the web server:

```bash
python web_app.py
```

3. Open your browser at `http://127.0.0.1:5000/`.

The web app shares the same `calories.db` file, so entries logged in the web UI and CLI all live together.

### USDA‑backed food search (web)

The web UI can look up nutrition data from USDA FoodData Central and scale it to the amount you ate.

1. Get a FoodData Central API key from USDA.
2. Set this environment variable in your shell before running `web_app.py`:

```bash
export USDA_FDC_API_KEY="your-api-key-here"
```

3. In the web app, click **“search USDA foods”** on the Today screen:
   - Search by name (e.g. “chicken breast”, “apple”).
   - Pick a result.
   - Enter how many servings you had and choose a meal (breakfast / lunch / dinner / snack).
   - The app saves the entry with calories, protein, carbs, and fat scaled to your serving.

### Basic flow (CLI)

- **Log food**: pick option `1`, type the food name, calories, and any notes.
- **See today**: pick option `2` to see everything you logged today and the total.
- **See another day**: pick option `3` and enter a date like `2026-03-03`.
- **7‑day summary**: pick option `4` to see total calories per day for the last week.

