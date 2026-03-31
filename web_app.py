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
    get_top_favorite_foods,
    add_weight_log,
    get_weight_logs,
    get_weight_trend,
    delete_weight_log,
    add_wellness_log,
    get_today_wellness_summary,
    get_wellness_logs,
    get_wellness_goals,
    set_wellness_goal,
    delete_wellness_log,
    create_recipe,
    add_recipe_ingredient,
    get_recipes,
    get_recipe_by_id,
    update_recipe,
    delete_recipe,
    calculate_recipe_macros,
    log_recipe,
    lookup_barcode,
    add_barcode_mapping,
    get_barcode_history,
    export_all_user_data,
    import_entries_from_csv,
    import_weight_from_csv,
    import_wellness_from_csv,
)
from usda_api import UsdaFood, UsdaSearchResponse, search_foods, search_foods_by_barcode


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


@app.route("/favorites", methods=["GET"])
@login_required
def favorites():
    """Show top 10 most-logged foods as quick-add buttons."""
    favorites = get_top_favorite_foods(current_user.id, limit=10)
    return render_template("favorites.html", favorites=favorites)


@app.route("/favorites/<food_name>/log", methods=["POST"])
@login_required
def log_favorite(food_name: str):
    """Quick-add entry from favorite."""
    favorites = get_top_favorite_foods(current_user.id, limit=10)
    fav = next((f for f in favorites if f["food"] == food_name), None)

    if not fav:
        return redirect(url_for("index"))

    # Use average calories from history
    avg_calories = int(fav["avg_calories"]) if fav["avg_calories"] else 0
    add_entry(
        food=food_name,
        calories=avg_calories,
        user_id=current_user.id,
    )
    return redirect(url_for("index"))


@app.route("/weight", methods=["GET"])
@login_required
def weight_view():
    """Show weight tracking dashboard."""
    logs = get_weight_logs(current_user.id, limit=90)
    trend = get_weight_trend(current_user.id, days=30)
    return render_template("weight.html", logs=logs, trend=trend)


@app.route("/weight", methods=["POST"])
@login_required
def add_weight():
    """Add weight log entry."""
    logged_at = request.form.get("logged_at", "").strip()
    weight_raw = request.form.get("weight_kg", "").strip()
    notes = request.form.get("notes", "").strip() or None

    if not logged_at or not weight_raw:
        return redirect(url_for("weight_view"))

    try:
        weight_kg = float(weight_raw)
        if weight_kg <= 0 or weight_kg > 500:
            return redirect(url_for("weight_view"))
    except ValueError:
        return redirect(url_for("weight_view"))

    add_weight_log(current_user.id, logged_at, weight_kg, notes)
    return redirect(url_for("weight_view"))


@app.route("/weight/<int:log_id>/delete", methods=["POST"])
@login_required
def delete_weight(log_id: int):
    """Delete weight log entry."""
    delete_weight_log(current_user.id, log_id)
    return redirect(url_for("weight_view"))


# ===== Feature 8: Wellness Tracking Routes =====


@app.route("/wellness", methods=["GET"])
@login_required
def wellness_view():
    """Show wellness tracking dashboard."""
    today_summary = get_today_wellness_summary(current_user.id)
    goals = get_wellness_goals(current_user.id)
    water_logs = get_wellness_logs(current_user.id, "water_ml", days=30)
    caffeine_logs = get_wellness_logs(current_user.id, "caffeine_mg", days=30)

    return render_template(
        "wellness.html",
        today_summary=today_summary,
        goals=goals,
        water_logs=water_logs,
        caffeine_logs=caffeine_logs,
    )


@app.route("/wellness", methods=["POST"])
@login_required
def add_wellness():
    """Add new wellness log entry."""
    log_date_str = request.form.get("log_date", "").strip()
    log_type = request.form.get("log_type", "").strip()
    value_str = request.form.get("value", "").strip()
    notes = request.form.get("notes", "").strip() or None

    if not log_date_str or not log_type or not value_str:
        return redirect(url_for("wellness_view"))

    try:
        value = float(value_str)
        if value <= 0:
            return redirect(url_for("wellness_view"))
    except ValueError:
        return redirect(url_for("wellness_view"))

    # Validate log_type is known
    valid_types = ["water_ml", "caffeine_mg", "vitamin_d_iu", "iron_mg"]
    if log_type not in valid_types:
        return redirect(url_for("wellness_view"))

    add_wellness_log(current_user.id, log_date_str, log_type, value, notes)
    return redirect(url_for("wellness_view"))


@app.route("/wellness/settings", methods=["GET"])
@login_required
def wellness_settings_view():
    """Show wellness goals settings."""
    goals = get_wellness_goals(current_user.id)
    return render_template("wellness_settings.html", goals=goals)


@app.route("/wellness/settings", methods=["POST"])
@login_required
def wellness_settings_save():
    """Save wellness goals."""
    water_goal = request.form.get("water_goal_ml", "").strip()
    caffeine_max = request.form.get("caffeine_max_mg", "").strip()
    vitamin_d_goal = request.form.get("vitamin_d_goal_iu", "").strip()
    iron_goal = request.form.get("iron_goal_mg", "").strip()

    try:
        if water_goal:
            float_val = float(water_goal)
            if float_val > 0:
                set_setting("water_goal_ml", water_goal, user_id=current_user.id)
        if caffeine_max:
            float_val = float(caffeine_max)
            if float_val > 0:
                set_setting("caffeine_max_mg", caffeine_max, user_id=current_user.id)
        if vitamin_d_goal:
            float_val = float(vitamin_d_goal)
            if float_val > 0:
                set_setting("vitamin_d_goal_iu", vitamin_d_goal, user_id=current_user.id)
        if iron_goal:
            float_val = float(iron_goal)
            if float_val > 0:
                set_setting("iron_goal_mg", iron_goal, user_id=current_user.id)
    except ValueError:
        pass

    return redirect(url_for("wellness_view"))


@app.route("/wellness/<int:log_id>/delete", methods=["POST"])
@login_required
def delete_wellness(log_id: int):
    """Delete wellness log entry."""
    delete_wellness_log(current_user.id, log_id)
    return redirect(url_for("wellness_view"))


# ===== Feature 9: Recipe Builder Routes =====


@app.route("/recipes", methods=["GET"])
@login_required
def recipes_list():
    """Show all recipes."""
    recipes = get_recipes(current_user.id)
    return render_template("recipes.html", recipes=recipes)


@app.route("/recipes/new", methods=["GET"])
@login_required
def recipes_new():
    """Show create recipe form."""
    return render_template("recipe_form.html", recipe=None)


@app.route("/recipes", methods=["POST"])
@login_required
def recipes_create():
    """Create new recipe."""
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    servings_str = request.form.get("servings", "1").strip()

    if not name:
        return redirect(url_for("recipes_list"))

    try:
        servings = float(servings_str) if servings_str else 1.0
        if servings <= 0:
            servings = 1.0
    except ValueError:
        servings = 1.0

    recipe_id = create_recipe(current_user.id, name, description, servings)
    return redirect(url_for("recipe_detail", recipe_id=recipe_id))


@app.route("/recipes/<int:recipe_id>", methods=["GET"])
@login_required
def recipe_detail(recipe_id: int):
    """Show recipe details."""
    recipe = get_recipe_by_id(recipe_id, current_user.id)
    if not recipe:
        return redirect(url_for("recipes_list"))
    return render_template("recipe_detail.html", recipe=recipe)


@app.route("/recipes/<int:recipe_id>/edit", methods=["GET"])
@login_required
def recipe_edit(recipe_id: int):
    """Show edit recipe form."""
    recipe = get_recipe_by_id(recipe_id, current_user.id)
    if not recipe:
        return redirect(url_for("recipes_list"))
    return render_template("recipe_form.html", recipe=recipe)


@app.route("/recipes/<int:recipe_id>", methods=["POST"])
@login_required
def recipe_update(recipe_id: int):
    """Update recipe."""
    recipe = get_recipe_by_id(recipe_id, current_user.id)
    if not recipe:
        return redirect(url_for("recipes_list"))

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    servings_str = request.form.get("servings", "1").strip()

    if not name:
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    try:
        servings = float(servings_str) if servings_str else 1.0
        if servings <= 0:
            servings = 1.0
    except ValueError:
        servings = 1.0

    update_recipe(recipe_id, current_user.id, name, description, servings)
    return redirect(url_for("recipe_detail", recipe_id=recipe_id))


@app.route("/recipes/<int:recipe_id>/delete", methods=["POST"])
@login_required
def recipe_delete(recipe_id: int):
    """Delete recipe."""
    delete_recipe(recipe_id, current_user.id)
    return redirect(url_for("recipes_list"))


@app.route("/recipes/<int:recipe_id>/log", methods=["POST"])
@login_required
def recipe_log(recipe_id: int):
    """Log recipe as food entry."""
    servings_str = request.form.get("servings", "1").strip()
    try:
        servings = float(servings_str)
        if servings <= 0:
            servings = 1.0
    except ValueError:
        servings = 1.0

    log_recipe(recipe_id, current_user.id, servings)
    return redirect(url_for("index"))


# Feature 10: Barcode Scanning

@app.route("/barcode")
@login_required
def barcode():
    """Show barcode scanner interface."""
    history = get_barcode_history(current_user.id, limit=10)
    return render_template("barcode.html", history=history)


@app.route("/barcode/search", methods=["GET"])
@login_required
def barcode_search():
    """Search for food by EAN code (AJAX endpoint)."""
    ean_code = request.args.get("ean", "").strip()
    if not ean_code:
        return {"error": "EAN code required"}, 400

    # Try cached lookup first
    cached = lookup_barcode(ean_code, current_user.id)
    if cached:
        return {
            "success": True,
            "ean_code": cached["ean_code"],
            "fdc_id": cached["fdc_id"],
            "food_name": cached["food_name"],
            "scan_count": cached["scan_count"],
            "from_cache": True,
        }

    # Query USDA API
    result = search_foods_by_barcode(ean_code)
    if result.error:
        return {"error": result.error}, 400

    if not result.foods:
        return {"error": f"No food found for barcode {ean_code}"}, 404

    # Return first match and cache it
    food = result.foods[0]
    add_barcode_mapping(ean_code, food.fdc_id, food.description)

    return {
        "success": True,
        "ean_code": ean_code,
        "fdc_id": food.fdc_id,
        "food_name": food.description,
        "brand": food.brand,
        "calories": food.calories,
        "protein_g": food.protein_g,
        "carbs_g": food.carbs_g,
        "fat_g": food.fat_g,
        "from_cache": False,
    }


@app.route("/barcode/history")
@login_required
def barcode_history():
    """Show recently scanned barcodes."""
    history = get_barcode_history(current_user.id, limit=20)
    return render_template("barcode_history.html", history=history)


# Feature 11: Bulk Import/Export

@app.route("/import", methods=["GET", "POST"])
@login_required
def import_data():
    """Import data from CSV file."""
    if request.method == "GET":
        return render_template("import.html")

    # Handle POST
    import_type = request.form.get("import_type", "entries").strip()

    if "file" not in request.files:
        flash("No file uploaded", "error")
        return render_template("import.html")

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected", "error")
        return render_template("import.html")

    try:
        # Read file content
        content = file.read().decode("utf-8")
        lines = [line.strip() for line in content.split("\n") if line.strip()]

        if not lines:
            flash("CSV file is empty", "error")
            return render_template("import.html")

        count, errors = 0, []

        if import_type == "entries":
            count, errors = import_entries_from_csv(current_user.id, lines)
        elif import_type == "weight":
            count, errors = import_weight_from_csv(current_user.id, lines)
        elif import_type == "wellness":
            count, errors = import_wellness_from_csv(current_user.id, lines)
        else:
            flash("Invalid import type", "error")
            return render_template("import.html")

        if count > 0:
            flash(f"Imported {count} records successfully!", "success")
        if errors:
            error_msg = "; ".join(errors[:5])
            if len(errors) > 5:
                error_msg += f"; ... and {len(errors) - 5} more errors"
            flash(f"Errors: {error_msg}", "warning")

        return render_template("import.html", result={"count": count, "errors": errors})

    except Exception as e:
        flash(f"Import failed: {str(e)}", "error")
        return render_template("import.html")


@app.route("/export")
@login_required
def export_data():
    """Export user data as JSON."""
    data = export_all_user_data(current_user.id)

    if not data:
        flash("No data to export", "error")
        return redirect(url_for("index"))

    import json
    response = make_response(json.dumps(data, indent=2))
    response.headers["Content-Disposition"] = f"attachment;filename=food_tracker_export_{date.today()}.json"
    response.headers["Content-Type"] = "application/json"
    return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    app.run(debug=debug, use_reloader=False, port=port)

