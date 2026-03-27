import os
from datetime import date, datetime
from typing import Optional

from flask import Flask, redirect, render_template, request, url_for, make_response, flash
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)

from main import (
    Food,
    User,
    add_entry,
    fetch_entries_for_date,
    fetch_recent_days,
    get_food_by_id,
    get_or_create_food,
    init_db,
    fetch_all_entries,
    get_calorie_goal,
    set_setting,
    create_user,
    get_user_by_username,
    get_user_by_id,
    verify_password,
    get_entry_by_id,
    update_entry,
    delete_entry,
    get_macro_targets,
    set_macro_target,
    add_to_search_history,
    get_search_history,
    create_meal_template,
    get_meal_templates,
    delete_meal_template,
    create_entry_from_template,
    get_week_summary,
    get_macro_trends,
)
from usda_api import UsdaFood, UsdaSearchResponse, search_foods


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."

init_db()


# flask-login requires a user class that implements UserMixin
class LoginUser(UserMixin):
    def __init__(self, user: User):
        self._user = user

    def get_id(self):
        return str(self._user.id)

    @property
    def username(self):
        return self._user.username

    @property
    def id(self):
        return self._user.id


@login_manager.user_loader
def load_user(user_id: str):
    user = get_user_by_id(int(user_id))
    return LoginUser(user) if user else None


@app.route("/", methods=["GET"])
@login_required
def index():
    today = date.today()
    entries = fetch_entries_for_date(today, user_id=current_user.id)
    total = sum(e.calories for e in entries)
    total_protein = sum(e.protein_g or 0 for e in entries)
    total_carbs = sum(e.carbs_g or 0 for e in entries)
    total_fat = sum(e.fat_g or 0 for e in entries)
    goal = get_calorie_goal(user_id=current_user.id)
    protein_goal, carbs_goal, fat_goal = get_macro_targets(user_id=current_user.id)
    return render_template(
        "index.html",
        entries=entries,
        total=total,
        today=today,
        goal=goal,
        total_protein=total_protein,
        total_carbs=total_carbs,
        total_fat=total_fat,
        protein_goal=protein_goal,
        carbs_goal=carbs_goal,
        fat_goal=fat_goal,
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

    add_entry(food=food, calories=calories, notes=notes, user_id=current_user.id)
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not username or not password:
            error = "Username and password are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            user = create_user(username, password)
            if user is None:
                error = f'Username "{username}" is already taken.'
            else:
                login_user(LoginUser(user))
                return redirect(url_for("index"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if not user or not verify_password(user, password):
            error = "Invalid username or password."
        else:
            login_user(LoginUser(user))
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/day/<day_str>", methods=["GET"])
@login_required
def day_view(day_str: str):
    try:
        chosen = date.fromisoformat(day_str)
    except ValueError:
        return redirect(url_for("index"))
    entries = fetch_entries_for_date(chosen, user_id=current_user.id)
    total = sum(e.calories for e in entries)
    total_protein = sum(e.protein_g or 0 for e in entries)
    total_carbs = sum(e.carbs_g or 0 for e in entries)
    total_fat = sum(e.fat_g or 0 for e in entries)
    protein_goal, carbs_goal, fat_goal = get_macro_targets(user_id=current_user.id)
    return render_template(
        "day.html",
        entries=entries,
        total=total,
        day=chosen,
        total_protein=total_protein,
        total_carbs=total_carbs,
        total_fat=total_fat,
        protein_goal=protein_goal,
        carbs_goal=carbs_goal,
        fat_goal=fat_goal,
    )


@app.route("/history", methods=["GET"])
@login_required
def history():
    rows = fetch_recent_days(user_id=current_user.id, limit=60)
    days = [
        {"day": r["day"], "total_calories": r["total_calories"] or 0, "entry_count": r["items"]}
        for r in rows
    ]
    return render_template("history.html", days=days)


@app.route("/foods/search", methods=["GET", "POST"])
@login_required
def foods_search():
    query = ""
    results: list[UsdaFood] = []
    error: str | None = None
    recent_searches = get_search_history(user_id=current_user.id, limit=10)
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            r: UsdaSearchResponse = search_foods(query)
            results = r.foods
            error = r.error
            add_to_search_history(query, current_user.id, len(results))
    return render_template(
        "search.html",
        query=query,
        results=results,
        error=error,
        recent_searches=recent_searches,
    )


@app.route("/foods/select", methods=["POST"])
@login_required
def foods_select():
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

    food = get_or_create_food(
        fdc_id=fdc_id,
        description=description,
        brand=brand,
        calories=_f("calories"),
        protein_g=_f("protein_g"),
        carbs_g=_f("carbs_g"),
        fat_g=_f("fat_g"),
    )
    return redirect(url_for("foods_log_get", food_id=food.id))


@app.route("/foods/log/<int:food_id>", methods=["GET"])
@login_required
def foods_log_get(food_id: int):
    food = get_food_by_id(food_id)
    if not food:
        return redirect(url_for("foods_search"))
    return render_template("log_food.html", food=food)


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
        return None if value is None else value * servings

    add_entry(
        food=f"{food.description}" + (f" ({food.brand})" if food.brand else ""),
        calories=int(round(_scaled(food.calories) or 0)),
        protein_g=_scaled(food.protein_g),
        carbs_g=_scaled(food.carbs_g),
        fat_g=_scaled(food.fat_g),
        meal=meal,
        servings=servings,
        notes=notes,
        user_id=current_user.id,
    )
    return redirect(url_for("index"))


@app.route("/entries", methods=["GET"])
@login_required
def entries_view():
    entries = fetch_all_entries(user_id=current_user.id)
    return render_template("entries.html", entries=entries)


@app.route("/entries/<int:entry_id>/edit", methods=["GET"])
@login_required
def edit_entry_get(entry_id: int):
    entry = get_entry_by_id(entry_id, current_user.id)
    if not entry:
        return redirect(url_for("index"))
    return render_template("edit_entry.html", entry=entry)


@app.route("/entries/<int:entry_id>/edit", methods=["POST"])
@login_required
def edit_entry_post(entry_id: int):
    entry = get_entry_by_id(entry_id, current_user.id)
    if not entry:
        return redirect(url_for("index"))

    food = request.form.get("food", "").strip()
    calories_raw = request.form.get("calories", "").strip()
    eaten_date = request.form.get("eaten_date", "").strip()
    eaten_time = request.form.get("eaten_time", "").strip()
    notes = request.form.get("notes", "").strip() or None
    meal = request.form.get("meal") or None

    try:
        servings = float(request.form.get("servings", "1") or "1")
    except ValueError:
        servings = 1.0

    try:
        protein_g = float(request.form.get("protein_g", "") or "")
    except ValueError:
        protein_g = None

    try:
        carbs_g = float(request.form.get("carbs_g", "") or "")
    except ValueError:
        carbs_g = None

    try:
        fat_g = float(request.form.get("fat_g", "") or "")
    except ValueError:
        fat_g = None

    if not food or not calories_raw or not eaten_date or not eaten_time:
        return redirect(url_for("index"))

    try:
        calories = int(calories_raw)
    except ValueError:
        return redirect(url_for("index"))

    # Combine date and time into ISO format
    try:
        eaten_at = f"{eaten_date}T{eaten_time}"
        # Validate the format
        datetime.fromisoformat(eaten_at)
    except (ValueError, AttributeError):
        return redirect(url_for("index"))

    update_entry(
        entry_id=entry_id,
        user_id=current_user.id,
        food=food,
        calories=calories,
        eaten_at=eaten_at,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        meal=meal,
        servings=servings if servings != 1.0 else None,
        notes=notes,
    )
    return redirect(url_for("index"))


@app.route("/entries/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete_entry_route(entry_id: int):
    delete_entry(entry_id, current_user.id)
    return redirect(url_for("index"))


@app.route("/export", methods=["GET"])
@login_required
def export_csv():
    import csv
    from io import StringIO

    entries = fetch_all_entries(user_id=current_user.id)
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "eaten_at", "food", "calories", "protein_g", "carbs_g", "fat_g", "meal", "servings", "notes"])
    for e in entries:
        writer.writerow([
            e.id, e.eaten_at.isoformat(), e.food, e.calories,
            "" if e.protein_g is None else e.protein_g,
            "" if e.carbs_g is None else e.carbs_g,
            "" if e.fat_g is None else e.fat_g,
            e.meal or "",
            "" if e.servings is None else e.servings,
            e.notes or "",
        ])
    response = make_response(si.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=entries.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@app.route("/settings", methods=["GET"])
@login_required
def settings_view():
    goal = get_calorie_goal(user_id=current_user.id)
    protein_t, carbs_t, fat_t = get_macro_targets(user_id=current_user.id)
    return render_template(
        "settings.html",
        goal=goal,
        protein_goal=protein_t,
        carbs_goal=carbs_t,
        fat_goal=fat_t,
        saved=False,
        active="settings",
    )


@app.route("/settings", methods=["POST"])
@login_required
def settings_save():
    raw = request.form.get("calorie_goal", "").strip()
    try:
        goal = int(raw)
        if goal > 0:
            set_setting("calorie_goal", str(goal), user_id=current_user.id)
    except ValueError:
        pass

    # Save macro targets
    for target, key in [
        ("protein_goal", "protein_goal_g"),
        ("carbs_goal", "carbs_goal_g"),
        ("fat_goal", "fat_goal_g"),
    ]:
        raw = request.form.get(target, "").strip()
        try:
            val = int(raw)
            if val > 0:
                set_setting(key, str(val), user_id=current_user.id)
        except ValueError:
            pass

    goal = get_calorie_goal(user_id=current_user.id)
    protein_t, carbs_t, fat_t = get_macro_targets(user_id=current_user.id)
    return render_template(
        "settings.html",
        goal=goal,
        protein_goal=protein_t,
        carbs_goal=carbs_t,
        fat_goal=fat_t,
        saved=True,
        active="settings",
    )


@app.route("/meals/save-template", methods=["POST"])
@login_required
def save_template():
    name = request.form.get("template_name", "").strip()
    food = request.form.get("food", "").strip()
    calories_raw = request.form.get("calories", "").strip()

    if not name or not food or not calories_raw:
        return redirect(url_for("index"))

    try:
        calories = int(calories_raw)
    except ValueError:
        return redirect(url_for("index"))

    try:
        protein_g = float(request.form.get("protein_g", "") or "")
    except ValueError:
        protein_g = None

    try:
        carbs_g = float(request.form.get("carbs_g", "") or "")
    except ValueError:
        carbs_g = None

    try:
        fat_g = float(request.form.get("fat_g", "") or "")
    except ValueError:
        fat_g = None

    create_meal_template(
        name=name,
        food=food,
        calories=calories,
        user_id=current_user.id,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
    )
    return redirect(url_for("index"))


@app.route("/meals/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def delete_template(template_id: int):
    delete_meal_template(template_id, current_user.id)
    return redirect(url_for("index"))


@app.route("/meals/templates/<int:template_id>/log", methods=["POST"])
@login_required
def log_from_template(template_id: int):
    create_entry_from_template(template_id, current_user.id)
    return redirect(url_for("index"))


@app.route("/insights", methods=["GET"])
@login_required
def insights():
    week_summary = get_week_summary(current_user.id)
    trends = get_macro_trends(current_user.id, weeks=4)
    protein_goal, carbs_goal, fat_goal = get_macro_targets(user_id=current_user.id)
    return render_template(
        "insights.html",
        week_summary=week_summary,
        trends=trends,
        protein_goal=protein_goal,
        carbs_goal=carbs_goal,
        fat_goal=fat_goal,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    app.run(debug=debug, use_reloader=False, port=port)

