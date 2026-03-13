import functools
import os
from datetime import date, datetime
from typing import Optional

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    make_response,
)

from main import (
    Food,
    add_entry,
    create_user,
    fetch_all_entries,
    fetch_entries_for_date,
    fetch_recent_days,
    get_food_by_id,
    get_or_create_food,
    get_user_by_username,
    init_db,
    verify_password,
)
from usda_api import UsdaFood, UsdaSearchResponse, search_foods


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")


init_db()


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def current_user_id() -> Optional[int]:
    return session.get("user_id")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "Username and password are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            user = create_user(username, password)
            if user is None:
                error = "That username is already taken. Please choose another."
            else:
                session["user_id"] = user.id
                session["username"] = user.username
                return redirect(url_for("index"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if user and verify_password(user, password):
            session["user_id"] = user.id
            session["username"] = user.username
            return redirect(url_for("index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# App routes (all protected)
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
@login_required
def index():
    today = date.today()
    uid = current_user_id()
    entries = fetch_entries_for_date(today, user_id=uid)
    total = sum(e.calories for e in entries)
    return render_template(
        "index.html",
        entries=entries,
        total=total,
        today=today,
        username=session.get("username"),
    )


@app.route("/add", methods=["POST"])
@login_required
def add():
    food = request.form.get("food", "").strip()
    calories_raw = request.form.get("calories", "").strip()
    notes = request.form.get("notes", "").strip() or None

    if not food:
        return redirect(url_for("index"))

    try:
        calories = int(calories_raw)
    except ValueError:
        return redirect(url_for("index"))

    add_entry(food=food, calories=calories, notes=notes, user_id=current_user_id())
    return redirect(url_for("index"))


@app.route("/day/<day_str>", methods=["GET"])
@login_required
def day_view(day_str: str):
    try:
        chosen = date.fromisoformat(day_str)
    except ValueError:
        return redirect(url_for("index"))

    entries = fetch_entries_for_date(chosen, user_id=current_user_id())
    total = sum(e.calories for e in entries)
    return render_template(
        "day.html",
        entries=entries,
        total=total,
        day=chosen,
        username=session.get("username"),
    )


@app.route("/history", methods=["GET"])
@login_required
def history():
    rows = fetch_recent_days(limit=7, user_id=current_user_id())
    items = [
        {
            "day": r["day"],
            "total_calories": r["total_calories"] or 0,
            "items": r["items"],
        }
        for r in rows
    ]
    return render_template("history.html", days=items, username=session.get("username"))


@app.route("/foods/search", methods=["GET", "POST"])
@login_required
def foods_search():
    query = ""
    results: list[UsdaFood] = []
    error: str | None = None
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            r: UsdaSearchResponse = search_foods(query)
            results = r.foods
            error = r.error
    return render_template(
        "search.html",
        query=query,
        results=results,
        error=error,
        username=session.get("username"),
    )


@app.route("/foods/select", methods=["POST"])
@login_required
def foods_select():
    """Persist a selected USDA food locally and move to the logging screen."""
    try:
        fdc_id = int(request.form.get("fdc_id", "0"))
    except ValueError:
        return redirect(url_for("foods_search"))

    description = request.form.get("description", "").strip() or "Food"
    brand = request.form.get("brand") or None

    def _f(name: str):
        raw = request.form.get(name)
        try:
            return float(raw) if raw not in (None, "", "None") else None
        except ValueError:
            return None

    calories = _f("calories")
    protein_g = _f("protein_g")
    carbs_g = _f("carbs_g")
    fat_g = _f("fat_g")

    food = get_or_create_food(
        fdc_id=fdc_id,
        description=description,
        brand=brand,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
    )
    return redirect(url_for("foods_log_get", food_id=food.id))


@app.route("/foods/log/<int:food_id>", methods=["GET"])
@login_required
def foods_log_get(food_id: int):
    food = get_food_by_id(food_id)
    if not food:
        return redirect(url_for("foods_search"))
    return render_template("log_food.html", food=food, username=session.get("username"))


@app.route("/foods/log/<int:food_id>", methods=["POST"])
@login_required
def foods_log_post(food_id: int):
    food = get_food_by_id(food_id)
    if not food:
        return redirect(url_for("foods_search"))

    try:
        servings = float(request.form.get("servings", "1") or "1")
    except ValueError:
        servings = 1.0

    meal = request.form.get("meal") or None
    notes = request.form.get("notes", "").strip() or None

    def _scaled(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return value * servings

    add_entry(
        food=f"{food.description}" + (f" ({food.brand})" if food.brand else ""),
        calories=int(round(_scaled(food.calories) or 0)),
        protein_g=_scaled(food.protein_g),
        carbs_g=_scaled(food.carbs_g),
        fat_g=_scaled(food.fat_g),
        meal=meal,
        servings=servings,
        notes=notes,
        user_id=current_user_id(),
    )

    return redirect(url_for("index"))


@app.route("/entries", methods=["GET"])
@login_required
def entries_view():
    """Show a dedicated page with all logged entries (newest first)."""
    entries = fetch_all_entries(user_id=current_user_id())
    return render_template("entries.html", entries=entries, username=session.get("username"))


@app.route("/export", methods=["GET"])
@login_required
def export_csv():
    """Return all entries as a CSV download."""
    entries = fetch_all_entries(user_id=current_user_id())
    import csv
    from io import StringIO

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow([
        "id",
        "eaten_at",
        "food",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
        "meal",
        "servings",
        "notes",
    ])
    for e in entries:
        writer.writerow([
            e.id,
            e.eaten_at.isoformat(),
            e.food,
            e.calories,
            "" if e.protein_g is None else f"{e.protein_g}",
            "" if e.carbs_g is None else f"{e.carbs_g}",
            "" if e.fat_g is None else f"{e.fat_g}",
            e.meal or "",
            "" if e.servings is None else f"{e.servings}",
            e.notes or "",
        ])

    response = make_response(si.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=entries.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=True, use_reloader=False, port=port)
