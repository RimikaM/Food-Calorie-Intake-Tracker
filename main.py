import sqlite3
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional


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


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        # Best-effort migration if table existed before columns were added.
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
                # Column already exists or table freshly created.
                pass


def add_entry(
    food: str,
    calories: int,
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
            INSERT INTO entries (eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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


def fetch_entries_for_date(day: date) -> List[Entry]:
    day_str = day.isoformat()
    start = f"{day_str}T00:00"
    end = f"{day_str}T23:59"
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id,
                   eaten_at,
                   food,
                   calories,
                   protein_g,
                   carbs_g,
                   fat_g,
                   meal,
                   servings,
                   notes
            FROM entries
            WHERE eaten_at BETWEEN ? AND ?
            ORDER BY eaten_at ASC
            """,
            (start, end),
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


def fetch_all_entries() -> list[Entry]:
    """Return all logged entries, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id,
                   eaten_at,
                   food,
                   calories,
                   protein_g,
                   carbs_g,
                   fat_g,
                   meal,
                   servings,
                   notes
            FROM entries
            ORDER BY eaten_at DESC
            """
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


def fetch_recent_days(limit: int = 7):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT substr(eaten_at, 1, 10) as day,
                   SUM(calories) as total_calories,
                   COUNT(*) as items
            FROM entries
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (limit,),
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

