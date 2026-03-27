import sqlite3
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

from werkzeug.security import generate_password_hash, check_password_hash


DB_PATH = Path(__file__).with_name("calories.db")


@dataclass
class Entry:
    id: int
    eaten_at: datetime
    food: str
    calories: int
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]
    meal: Optional[str]
    servings: Optional[float]
    notes: Optional[str]


@dataclass
class Food:
    id: int
    fdc_id: int
    description: str
    brand: Optional[str]
    calories: Optional[float]
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]


@dataclass
class User:
    id: int
    username: str
    password_hash: str


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                eaten_at TEXT NOT NULL,
                food TEXT NOT NULL,
                calories INTEGER NOT NULL,
                protein_g REAL,
                carbs_g REAL,
                fat_g REAL,
                meal TEXT,
                servings REAL,
                notes TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS foods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fdc_id INTEGER UNIQUE NOT NULL,
                description TEXT NOT NULL,
                brand TEXT,
                calories REAL,
                protein_g REAL,
                carbs_g REAL,
                fat_g REAL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER NOT NULL REFERENCES users(id),
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                query TEXT NOT NULL,
                searched_at TEXT NOT NULL,
                result_count INTEGER,
                UNIQUE(user_id, query)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meal_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL,
                food_description TEXT NOT NULL,
                calories INTEGER NOT NULL,
                protein_g REAL,
                carbs_g REAL,
                fat_g REAL,
                created_at TEXT NOT NULL
            );
            """
        )
        # Best-effort migrations for pre-existing DBs.
        for column_sql in (
            "protein_g REAL",
            "carbs_g REAL",
            "fat_g REAL",
            "meal TEXT",
            "servings REAL",
        ):
            try:
                conn.execute(f"ALTER TABLE entries ADD COLUMN {column_sql}")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN user_id INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE settings ADD COLUMN user_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # If settings table still has the old single-column PK (key TEXT PRIMARY KEY),
        # migrate it to the composite (user_id, key) PK required by ON CONFLICT upserts.
        old_schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='settings'"
        ).fetchone()
        if old_schema and "user_id" not in old_schema["sql"].split("PRIMARY KEY")[0].strip().upper().split()[-1:][0] if old_schema["sql"] else False:
            pass  # already composite
        try:
            # Detect old schema: PRIMARY KEY is just (key), not (user_id, key)
            pk_info = conn.execute("PRAGMA table_info(settings)").fetchall()
            pk_cols = [row["name"] for row in pk_info if row["pk"] > 0]
            if pk_cols == ["key"]:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings_migration (
                        user_id INTEGER NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        PRIMARY KEY (user_id, key)
                    )
                """)
                conn.execute("""
                    INSERT OR IGNORE INTO settings_migration (user_id, key, value)
                    SELECT user_id, key, value FROM settings WHERE user_id IS NOT NULL
                """)
                conn.execute("DROP TABLE settings")
                conn.execute("ALTER TABLE settings_migration RENAME TO settings")
        except sqlite3.OperationalError:
            pass


def add_entry(
    food: str,
    calories: int,
    user_id: int,
    notes: Optional[str] = None,
    protein_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    meal: Optional[str] = None,
    servings: Optional[float] = None,
) -> None:
    now = datetime.now().isoformat(timespec="minutes")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO entries (user_id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                now,
                food.strip(),
                calories,
                protein_g,
                carbs_g,
                fat_g,
                meal,
                servings,
                notes.strip() if notes else None,
            ),
        )


def get_entry_by_id(entry_id: int, user_id: int) -> Optional[Entry]:
    """Fetch a single entry by ID, with user ownership check."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes
            FROM entries
            WHERE id = ? AND user_id = ?
            """,
            (entry_id, user_id),
        ).fetchone()
    if not row:
        return None
    return Entry(
        id=row["id"],
        eaten_at=datetime.fromisoformat(row["eaten_at"]),
        food=row["food"],
        calories=row["calories"],
        protein_g=row["protein_g"],
        carbs_g=row["carbs_g"],
        fat_g=row["fat_g"],
        meal=row["meal"],
        servings=row["servings"],
        notes=row["notes"],
    )


def update_entry(
    entry_id: int,
    user_id: int,
    food: str,
    calories: int,
    eaten_at: Optional[str] = None,
    protein_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    meal: Optional[str] = None,
    servings: Optional[float] = None,
    notes: Optional[str] = None,
) -> bool:
    """Update an entry with user ownership check. Returns True if successful."""
    # eaten_at should be ISO format string like "2026-03-27T14:30"
    # If not provided, keep existing value
    with get_connection() as conn:
        # First verify ownership
        existing = conn.execute(
            "SELECT id FROM entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        ).fetchone()
        if not existing:
            return False

        # Update the entry
        conn.execute(
            """
            UPDATE entries
            SET food = ?, calories = ?, eaten_at = COALESCE(?, eaten_at),
                protein_g = ?, carbs_g = ?, fat_g = ?,
                meal = ?, servings = ?, notes = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                food.strip(),
                calories,
                eaten_at,
                protein_g,
                carbs_g,
                fat_g,
                meal,
                servings,
                notes.strip() if notes else None,
                entry_id,
                user_id,
            ),
        )
        return True


def delete_entry(entry_id: int, user_id: int) -> bool:
    """Delete an entry with user ownership check. Returns True if successful."""
    with get_connection() as conn:
        # Verify ownership before deleting
        existing = conn.execute(
            "SELECT id FROM entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        ).fetchone()
        if not existing:
            return False

        conn.execute(
            "DELETE FROM entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        )
        return True


def fetch_entries_for_date(day: date, user_id: int) -> List[Entry]:
    day_str = day.isoformat()
    start = f"{day_str}T00:00"
    end = f"{day_str}T23:59"
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes
            FROM entries
            WHERE user_id = ? AND eaten_at BETWEEN ? AND ?
            ORDER BY eaten_at ASC
            """,
            (user_id, start, end),
        ).fetchall()
    entries: List[Entry] = []
    for r in rows:
        entries.append(
            Entry(
                id=r["id"],
                eaten_at=datetime.fromisoformat(r["eaten_at"]),
                food=r["food"],
                calories=r["calories"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                meal=r["meal"],
                servings=r["servings"],
                notes=r["notes"],
            )
        )
    return entries


def fetch_all_entries(user_id: int) -> list[Entry]:
    """Return all logged entries for a user, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes
            FROM entries
            WHERE user_id = ?
            ORDER BY eaten_at DESC
            """,
            (user_id,),
        ).fetchall()
    entries: list[Entry] = []
    for r in rows:
        entries.append(
            Entry(
                id=r["id"],
                eaten_at=datetime.fromisoformat(r["eaten_at"]),
                food=r["food"],
                calories=r["calories"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                meal=r["meal"],
                servings=r["servings"],
                notes=r["notes"],
            )
        )
    return entries


def fetch_recent_days(user_id: int, limit: int = 7):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT substr(eaten_at, 1, 10) as day,
                   SUM(calories) as total_calories,
                   COUNT(*) as items
            FROM entries
            WHERE user_id = ?
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return rows


def get_or_create_food(
    fdc_id: int,
    description: str,
    brand: Optional[str],
    calories: Optional[float],
    protein_g: Optional[float],
    carbs_g: Optional[float],
    fat_g: Optional[float],
) -> Food:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, fdc_id, description, brand, calories, protein_g, carbs_g, fat_g FROM foods WHERE fdc_id = ?",
            (fdc_id,),
        ).fetchone()
        if row:
            return Food(
                id=row["id"],
                fdc_id=row["fdc_id"],
                description=row["description"],
                brand=row["brand"],
                calories=row["calories"],
                protein_g=row["protein_g"],
                carbs_g=row["carbs_g"],
                fat_g=row["fat_g"],
            )

        cur = conn.execute(
            """
            INSERT INTO foods (fdc_id, description, brand, calories, protein_g, carbs_g, fat_g)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (fdc_id, description, brand, calories, protein_g, carbs_g, fat_g),
        )
        new_id = cur.lastrowid
        return Food(
            id=new_id,
            fdc_id=fdc_id,
            description=description,
            brand=brand,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
        )


def get_food_by_id(food_id: int) -> Optional[Food]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, fdc_id, description, brand, calories, protein_g, carbs_g, fat_g FROM foods WHERE id = ?",
            (food_id,),
        ).fetchone()
        if not row:
            return None
        return Food(
            id=row["id"],
            fdc_id=row["fdc_id"],
            description=row["description"],
            brand=row["brand"],
            calories=row["calories"],
            protein_g=row["protein_g"],
            carbs_g=row["carbs_g"],
            fat_g=row["fat_g"],
        )


def get_setting(key: str, user_id: int, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str, user_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, key, value),
        )


def get_calorie_goal(user_id: int) -> Optional[int]:
    raw = get_setting("calorie_goal", user_id)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def get_macro_targets(user_id: int) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Return (protein_goal_g, carbs_goal_g, fat_goal_g) from settings."""
    protein = get_setting("protein_goal_g", user_id)
    carbs = get_setting("carbs_goal_g", user_id)
    fat = get_setting("fat_goal_g", user_id)
    try:
        protein_int = int(protein) if protein is not None else None
        carbs_int = int(carbs) if carbs is not None else None
        fat_int = int(fat) if fat is not None else None
        return (protein_int, carbs_int, fat_int)
    except ValueError:
        return (None, None, None)


def set_macro_target(target_type: str, value: int, user_id: int) -> None:
    """Set a macro target. target_type should be 'protein_goal_g', 'carbs_goal_g', or 'fat_goal_g'."""
    set_setting(target_type, str(value), user_id)


def add_to_search_history(query: str, user_id: int, result_count: int) -> None:
    """Add or update a search in search history."""
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO search_history (user_id, query, searched_at, result_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, query) DO UPDATE SET searched_at = ?, result_count = ?
            """,
            (user_id, query.strip(), now, result_count, now, result_count),
        )


def get_search_history(user_id: int, limit: int = 10) -> List[dict]:
    """Get recent searches for a user."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT query, searched_at, result_count
            FROM search_history
            WHERE user_id = ?
            ORDER BY searched_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def create_meal_template(
    name: str,
    food: str,
    calories: int,
    user_id: int,
    protein_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    fat_g: Optional[float] = None,
) -> int:
    """Create a meal template. Returns the template id."""
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO meal_templates (user_id, name, food_description, calories, protein_g, carbs_g, fat_g, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                name.strip(),
                food.strip(),
                calories,
                protein_g,
                carbs_g,
                fat_g,
                now,
            ),
        )
        return cur.lastrowid


def get_meal_templates(user_id: int) -> List[dict]:
    """Get all meal templates for a user."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, food_description, calories, protein_g, carbs_g, fat_g, created_at
            FROM meal_templates
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_meal_template(template_id: int, user_id: int) -> bool:
    """Delete a meal template with user ownership check. Returns True if successful."""
    with get_connection() as conn:
        # Verify ownership
        existing = conn.execute(
            "SELECT id FROM meal_templates WHERE id = ? AND user_id = ?",
            (template_id, user_id),
        ).fetchone()
        if not existing:
            return False

        conn.execute(
            "DELETE FROM meal_templates WHERE id = ? AND user_id = ?",
            (template_id, user_id),
        )
        return True


def create_entry_from_template(template_id: int, user_id: int) -> bool:
    """Create an entry from a meal template. Returns True if successful."""
    with get_connection() as conn:
        template = conn.execute(
            "SELECT food_description, calories, protein_g, carbs_g, fat_g FROM meal_templates WHERE id = ? AND user_id = ?",
            (template_id, user_id),
        ).fetchone()
        if not template:
            return False

    # Create entry with current timestamp
    add_entry(
        food=template["food_description"],
        calories=template["calories"],
        user_id=user_id,
        protein_g=template["protein_g"],
        carbs_g=template["carbs_g"],
        fat_g=template["fat_g"],
    )
    return True


def get_week_summary(user_id: int, end_date: Optional[date] = None) -> dict:
    """Get weekly summary (totals and averages) for a user. end_date defaults to today."""
    if end_date is None:
        end_date = date.today()

    # Calculate week start (Monday) and end (Sunday)
    week_start = end_date - timedelta(days=end_date.weekday())
    week_end = week_start + timedelta(days=6)

    week_start_str = week_start.isoformat()
    week_end_str = week_end.isoformat()
    start_time = f"{week_start_str}T00:00"
    end_time = f"{week_end_str}T23:59"

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as entry_count,
                SUM(calories) as total_calories,
                COUNT(DISTINCT DATE(eaten_at)) as days_logged,
                SUM(COALESCE(protein_g, 0)) as total_protein_g,
                SUM(COALESCE(carbs_g, 0)) as total_carbs_g,
                SUM(COALESCE(fat_g, 0)) as total_fat_g,
                AVG(CASE WHEN protein_g IS NOT NULL THEN protein_g END) as avg_protein_g,
                AVG(CASE WHEN carbs_g IS NOT NULL THEN carbs_g END) as avg_carbs_g,
                AVG(CASE WHEN fat_g IS NOT NULL THEN fat_g END) as avg_fat_g
            FROM entries
            WHERE user_id = ? AND eaten_at BETWEEN ? AND ?
            """,
            (user_id, start_time, end_time),
        ).fetchone()

    return {
        "week_start": week_start,
        "week_end": week_end,
        "entry_count": row["entry_count"] or 0,
        "days_logged": row["days_logged"] or 0,
        "total_calories": row["total_calories"] or 0,
        "avg_calories": (row["total_calories"] or 0) / (row["days_logged"] or 1),
        "total_protein_g": row["total_protein_g"] or 0,
        "avg_protein_g": row["avg_protein_g"],
        "total_carbs_g": row["total_carbs_g"] or 0,
        "avg_carbs_g": row["avg_carbs_g"],
        "total_fat_g": row["total_fat_g"] or 0,
        "avg_fat_g": row["avg_fat_g"],
    }


def get_macro_trends(user_id: int, weeks: int = 4) -> List[dict]:
    """Get weekly summaries for past N weeks."""
    from datetime import timedelta

    today = date.today()
    trends = []

    for i in range(weeks - 1, -1, -1):
        end_date = today - timedelta(weeks=i)
        summary = get_week_summary(user_id, end_date)
        trends.append(summary)

    return trends


def create_user(username: str, password: str) -> Optional[User]:
    """Create a new user. Returns the User or None if the username is taken."""
    hashed = generate_password_hash(password)
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username.strip(), hashed),
            )
            return User(id=cur.lastrowid, username=username.strip(), password_hash=hashed)
    except sqlite3.IntegrityError:
        return None  # username already exists


def get_user_by_username(username: str) -> Optional[User]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    if not row:
        return None
    return User(id=row["id"], username=row["username"], password_hash=row["password_hash"])


def get_user_by_id(user_id: int) -> Optional[User]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return User(id=row["id"], username=row["username"], password_hash=row["password_hash"])


def verify_password(user: User, password: str) -> bool:
    return check_password_hash(user.password_hash, password)


def input_int(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
            if value < 0:
                print("Please enter a non-negative number.")
                continue
            return value
        except ValueError:
            print("Please enter a whole number (like 250).")


def input_date(prompt: str, default: Optional[date] = None) -> date:
    suffix = f" (default {default.isoformat()})" if default else ""
    while True:
        raw = input(prompt + suffix + ": ").strip()
        if not raw and default:
            return default
        try:
            # Accept formats like 2026-03-03
            return date.fromisoformat(raw)
        except ValueError:
            print("Use YYYY-MM-DD, e.g. 2026-03-03.")


def print_today() -> None:
    today = date.today()
    entries = fetch_entries_for_date(today)
    if not entries:
        print("\nNothing logged for today yet.")
        return

    print(f"\nToday – {today.isoformat()}")
    print("-" * 40)
    total = 0
    for e in entries:
        time_label = e.eaten_at.strftime("%H:%M")
        note_part = f"  ·  {e.notes}" if e.notes else ""
        print(f"[{time_label}] {e.food} – {e.calories} kcal{note_part}")
        total += e.calories
    print("-" * 40)
    print(f"Total: {total} kcal")


def print_for_specific_day() -> None:
    chosen = input_date("\nDate to view")
    entries = fetch_entries_for_date(chosen)
    if not entries:
        print(f"\nNothing logged for {chosen.isoformat()}.")
        return

    print(f"\n{chosen.isoformat()}")
    print("-" * 40)
    total = 0
    for e in entries:
        time_label = e.eaten_at.strftime("%H:%M")
        note_part = f"  ·  {e.notes}" if e.notes else ""
        print(f"[{time_label}] {e.food} – {e.calories} kcal{note_part}")
        total += e.calories
    print("-" * 40)
    print(f"Total: {total} kcal")


def print_recent_summary() -> None:
    rows = fetch_recent_days(limit=7)
    if not rows:
        print("\nNo history yet.")
        return

    print("\nLast 7 days")
    print("-" * 40)
    for r in rows:
        day = r["day"]
        total = r["total_calories"]
        items = r["items"]
        print(f"{day}: {total} kcal across {items} item(s)")


def add_entry_flow() -> None:
    print("\nLog something you ate ✨")
    food = input("Food / meal: ").strip()
    if not food:
        print("Skipping, no name given.")
        return
    calories = input_int("Calories (kcal): ")
    notes = input("Notes (optional): ").strip()
    if not notes:
        notes = None

    add_entry(food=food, calories=calories, notes=notes)
    print("Saved.")


def main_menu() -> None:
    init_db()

    print("\nWelcome to your calorie tracker")
    print("Type a number and press Enter.\n")

    while True:
        print("\nWhat do you want to do?")
        print("  1) Log food")
        print("  2) See today")
        print("  3) See another day")
        print("  4) 7-day summary")
        print("  0) Quit")

        choice = input("> ").strip()
        if choice == "1":
            add_entry_flow()
        elif choice == "2":
            print_today()
        elif choice == "3":
            print_for_specific_day()
        elif choice == "4":
            print_recent_summary()
        elif choice == "0":
            print("Bye, take care of yourself 💚")
            break
        else:
            print("Pick 0, 1, 2, 3, or 4.")


if __name__ == "__main__":
    main_menu()

