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

