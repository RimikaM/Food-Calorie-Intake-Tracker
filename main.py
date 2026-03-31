import os
import sqlite3
import psycopg2
import psycopg2.extras
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional

from werkzeug.security import generate_password_hash, check_password_hash


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


class SqliteCursor:
    """Wrapper for SQLite cursor to handle placeholder conversion."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        # Convert %s to ? for SQLite
        sql = sql.replace("%s", "?")
        # Handle RETURNING clause (PostgreSQL) - just remove it for SQLite
        if " RETURNING " in sql:
            sql = sql.split(" RETURNING ")[0]
        if params is None:
            return self._cursor.execute(sql)
        return self._cursor.execute(sql, params)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def commit(self):
        return self._cursor.commit()

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def safe_execute(cursor, sql, params, conn):
    """Execute SQL with automatic placeholder conversion for raw SQLite connections (like in tests)."""
    # If it's a raw sqlite3.Connection (from test monkeypatch), convert placeholders
    if isinstance(conn, sqlite3.Connection) and not isinstance(conn, SqliteConnection):
        sql = sql.replace("%s", "?")
        if " RETURNING " in sql:
            sql = sql.split(" RETURNING ")[0]
    cursor.execute(sql, params if params else ())



class SqliteConnection:
    """Wrapper for SQLite connection to handle placeholder conversion automatically."""

    def __init__(self, conn):
        self._conn = conn
        self.is_sqlite = True

    def cursor(self, *args, **kwargs):
        cur = self._conn.cursor(*args, **kwargs)
        return SqliteCursor(cur)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_connection():
    """Get a database connection. Uses PostgreSQL for production (Railway), SQLite for local development."""
    db_url = os.getenv("DATABASE_URL")

    if db_url:
        # Railway production: use PostgreSQL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://")
        conn = psycopg2.connect(db_url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        conn.is_sqlite = False
        return conn
    else:
        # Local development: use SQLite
        db_path = Path(__file__).with_name("calories.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return SqliteConnection(conn)


def normalize_connection(conn):
    """Ensure connection is properly wrapped for placeholder conversion."""
    # If it's a raw sqlite3.Connection (not wrapped), wrap it now
    if isinstance(conn, sqlite3.Connection) and not isinstance(conn, SqliteConnection):
        # Wrap the raw connection - likely from test monkeypatch
        wrapped = SqliteConnection.__new__(SqliteConnection)
        wrapped._conn = conn
        wrapped.is_sqlite = True
        wrapped.is_test = True  # Mark as borrowed from test - don't auto-close
        return wrapped
    return conn


def close_connection(conn):
    """Close connection only if it's not a borrowed test connection."""
    if isinstance(conn, SqliteConnection):
        if not getattr(conn, 'is_test', False):
            conn._conn.close()
    else:
        # Direct PostgreSQL connection
        conn.close()


def init_db() -> None:
    conn = normalize_connection(get_connection())
    try:
        # Create tables - use compatible syntax for both SQLite and PostgreSQL
        table_definitions = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            """,
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
            """,
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
            """,
            """
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER NOT NULL REFERENCES users(id),
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                query TEXT NOT NULL,
                searched_at TEXT NOT NULL,
                result_count INTEGER,
                UNIQUE(user_id, query)
            );
            """,
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
            """,
            """
            CREATE TABLE IF NOT EXISTS weight_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                logged_at TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                notes TEXT,
                UNIQUE(user_id, logged_at)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS wellness_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                log_date TEXT NOT NULL,
                log_type TEXT NOT NULL,
                value REAL NOT NULL,
                notes TEXT,
                UNIQUE(user_id, log_date, log_type)
            );
            """,
        ]

        cur = conn.cursor()
        for sql in table_definitions:
            try:
                cur.execute(sql)
            except (sqlite3.OperationalError, psycopg2.errors.DuplicateTable):
                # Table already exists, ignore
                pass

        conn.commit()
    finally:
        # Only close if it's a wrapped SqliteConnection and not borrowed from tests
        if isinstance(conn, SqliteConnection) and not getattr(conn, 'is_test', False):
            close_connection(conn)


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
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO entries (user_id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        conn.commit()
    finally:
        close_connection(conn)


def get_entry_by_id(entry_id: int, user_id: int) -> Optional[Entry]:
    """Fetch a single entry by ID, with user ownership check."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes
            FROM entries
            WHERE id = %s AND user_id = %s
            """,
            (entry_id, user_id),
        )
        row = cur.fetchone()
    finally:
        close_connection(conn)
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
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        # First verify ownership
        cur.execute(
            "SELECT id FROM entries WHERE id = %s AND user_id = %s",
            (entry_id, user_id),
        )
        existing = cur.fetchone()
        if not existing:
            return False

        # Update the entry
        cur.execute(
            """
            UPDATE entries
            SET food = %s, calories = %s, eaten_at = COALESCE(%s, eaten_at),
                protein_g = %s, carbs_g = %s, fat_g = %s,
                meal = %s, servings = %s, notes = %s
            WHERE id = %s AND user_id = %s
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
        conn.commit()
        return True
    finally:
        close_connection(conn)


def delete_entry(entry_id: int, user_id: int) -> bool:
    """Delete an entry with user ownership check. Returns True if successful."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        # Verify ownership before deleting
        cur.execute(
            "SELECT id FROM entries WHERE id = %s AND user_id = %s",
            (entry_id, user_id),
        )
        existing = cur.fetchone()
        if not existing:
            return False

        cur.execute(
            "DELETE FROM entries WHERE id = %s AND user_id = %s",
            (entry_id, user_id),
        )
        conn.commit()
        return True
    finally:
        close_connection(conn)


def fetch_entries_for_date(day: date, user_id: int) -> List[Entry]:
    day_str = day.isoformat()
    start = f"{day_str}T00:00"
    end = f"{day_str}T23:59"
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes
            FROM entries
            WHERE user_id = %s AND eaten_at BETWEEN %s AND %s
            ORDER BY eaten_at ASC
            """,
            (user_id, start, end),
        )
        rows = cur.fetchall()
    finally:
        close_connection(conn)
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
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, eaten_at, food, calories, protein_g, carbs_g, fat_g, meal, servings, notes
            FROM entries
            WHERE user_id = %s
            ORDER BY eaten_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    finally:
        close_connection(conn)
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
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT substring(eaten_at, 1, 10) as day,
                   SUM(calories) as total_calories,
                   COUNT(*) as items
            FROM entries
            WHERE user_id = %s
            GROUP BY day
            ORDER BY day DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    finally:
        close_connection(conn)
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
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, fdc_id, description, brand, calories, protein_g, carbs_g, fat_g FROM foods WHERE fdc_id = %s",
            (fdc_id,),
        )
        row = cur.fetchone()
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

        # Insert food - handle SQLite vs PostgreSQL
        cur.execute(
            """
            INSERT INTO foods (fdc_id, description, brand, calories, protein_g, carbs_g, fat_g)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (fdc_id, description, brand, calories, protein_g, carbs_g, fat_g),
        )

        if conn.is_sqlite:
            # SQLite: fetch lastrowid after insert (RETURNING was stripped)
            new_id = cur.lastrowid
        else:
            # PostgreSQL: fetch from RETURNING
            result = cur.fetchone()
            new_id = result["id"]

        conn.commit()
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
    finally:
        close_connection(conn)


def get_food_by_id(food_id: int) -> Optional[Food]:
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, fdc_id, description, brand, calories, protein_g, carbs_g, fat_g FROM foods WHERE id = %s",
            (food_id,),
        )
        row = cur.fetchone()
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
    finally:
        close_connection(conn)


def get_setting(key: str, user_id: int, default: Optional[str] = None) -> Optional[str]:
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM settings WHERE user_id = %s AND key = %s", (user_id, key)
        )
        row = cur.fetchone()
    finally:
        close_connection(conn)
    return row["value"] if row else default


def set_setting(key: str, value: str, user_id: int) -> None:
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO settings (user_id, key, value) VALUES (%s, %s, %s)
            ON CONFLICT(user_id, key) DO UPDATE SET value = EXCLUDED.value
            """,
            (user_id, key, value),
        )
        conn.commit()
    finally:
        close_connection(conn)


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
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO search_history (user_id, query, searched_at, result_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(user_id, query) DO UPDATE SET searched_at = EXCLUDED.searched_at, result_count = EXCLUDED.result_count
            """,
            (user_id, query.strip(), now, result_count),
        )
        conn.commit()
    finally:
        close_connection(conn)


def get_search_history(user_id: int, limit: int = 10) -> List[dict]:
    """Get recent searches for a user."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT query, searched_at, result_count
            FROM search_history
            WHERE user_id = %s
            ORDER BY searched_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    finally:
        close_connection(conn)
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
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO meal_templates (user_id, name, food_description, calories, protein_g, carbs_g, fat_g, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
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
        result = cur.fetchone()
        new_id = result["id"]
        conn.commit()
        return new_id
    finally:
        close_connection(conn)


def get_meal_templates(user_id: int) -> List[dict]:
    """Get all meal templates for a user."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, food_description, calories, protein_g, carbs_g, fat_g, created_at
            FROM meal_templates
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    finally:
        close_connection(conn)
    return [dict(row) for row in rows]


def delete_meal_template(template_id: int, user_id: int) -> bool:
    """Delete a meal template with user ownership check. Returns True if successful."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        # Verify ownership
        cur.execute(
            "SELECT id FROM meal_templates WHERE id = %s AND user_id = %s",
            (template_id, user_id),
        )
        existing = cur.fetchone()
        if not existing:
            return False

        cur.execute(
            "DELETE FROM meal_templates WHERE id = %s AND user_id = %s",
            (template_id, user_id),
        )
        conn.commit()
        return True
    finally:
        close_connection(conn)


def create_entry_from_template(template_id: int, user_id: int) -> bool:
    """Create an entry from a meal template. Returns True if successful."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT food_description, calories, protein_g, carbs_g, fat_g FROM meal_templates WHERE id = %s AND user_id = %s",
            (template_id, user_id),
        )
        template = cur.fetchone()
        if not template:
            return False
    finally:
        close_connection(conn)

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

    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) as entry_count,
                SUM(calories) as total_calories,
                COUNT(DISTINCT DATE(eaten_at::timestamp)) as days_logged,
                SUM(COALESCE(protein_g, 0)) as total_protein_g,
                SUM(COALESCE(carbs_g, 0)) as total_carbs_g,
                SUM(COALESCE(fat_g, 0)) as total_fat_g,
                AVG(CASE WHEN protein_g IS NOT NULL THEN protein_g END) as avg_protein_g,
                AVG(CASE WHEN carbs_g IS NOT NULL THEN carbs_g END) as avg_carbs_g,
                AVG(CASE WHEN fat_g IS NOT NULL THEN fat_g END) as avg_fat_g
            FROM entries
            WHERE user_id = %s AND eaten_at BETWEEN %s AND %s
            """,
            (user_id, start_time, end_time),
        )
        row = cur.fetchone()
    finally:
        close_connection(conn)

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


def get_top_favorite_foods(user_id: int, limit: int = 10) -> List[dict]:
    """Get most frequently logged foods for a user. Returns list of dicts with food name, times_logged, and avg_calories."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT food, COUNT(*) as times_logged, AVG(calories) as avg_calories
            FROM entries
            WHERE user_id = %s
            GROUP BY food
            ORDER BY times_logged DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    finally:
        close_connection(conn)
    return [dict(row) for row in rows]


def add_weight_log(user_id: int, logged_at: str, weight_kg: float, notes: str = None) -> bool:
    """Add weight log entry (upserts if same day)."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO weight_logs (user_id, logged_at, weight_kg, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(user_id, logged_at) DO UPDATE SET weight_kg = EXCLUDED.weight_kg, notes = EXCLUDED.notes
            """,
            (user_id, logged_at, weight_kg, notes),
        )
        conn.commit()
        return True
    finally:
        close_connection(conn)


def get_weight_logs(user_id: int, limit: int = 90) -> List[dict]:
    """Get weight logs for a user, newest first."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, logged_at, weight_kg, notes
            FROM weight_logs
            WHERE user_id = %s
            ORDER BY logged_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    finally:
        close_connection(conn)
    return [dict(row) for row in rows]


def get_weight_trend(user_id: int, days: int = 30) -> dict:
    """Get weight trend over past N days."""
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()

    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT MIN(weight_kg) as min_weight, MAX(weight_kg) as max_weight,
                   AVG(weight_kg) as avg_weight
            FROM weight_logs
            WHERE user_id = %s AND logged_at BETWEEN %s AND %s
            """,
            (user_id, start_date, end_date),
        )
        row = cur.fetchone()

        # Get current weight
        cur.execute(
            """
            SELECT weight_kg FROM weight_logs
            WHERE user_id = %s AND logged_at <= %s
            ORDER BY logged_at DESC
            LIMIT 1
            """,
            (user_id, end_date),
        )
        current = cur.fetchone()
        current_weight = current["weight_kg"] if current else None

        # Get weight change
        cur.execute(
            """
            SELECT weight_kg FROM weight_logs
            WHERE user_id = %s AND logged_at >= %s AND logged_at <= %s
            ORDER BY logged_at ASC
            LIMIT 1
            """,
            (user_id, start_date, end_date),
        )
        first = cur.fetchone()
        first_weight = first["weight_kg"] if first else None

        change = (current_weight - first_weight) if (current_weight and first_weight) else None

    finally:
        close_connection(conn)

    return {
        "current_weight": current_weight,
        "min_weight": row["min_weight"],
        "max_weight": row["max_weight"],
        "avg_weight": row["avg_weight"],
        "change_kg": change,
        "trend": "↑" if change and change > 0 else "↓" if change and change < 0 else "→",
    }


def delete_weight_log(user_id: int, log_id: int) -> bool:
    """Delete weight log with ownership check."""
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM weight_logs WHERE id = %s AND user_id = %s",
            (log_id, user_id),
        )
        existing = cur.fetchone()
        if not existing:
            return False

        cur.execute(
            "DELETE FROM weight_logs WHERE id = %s AND user_id = %s",
            (log_id, user_id),
        )
        conn.commit()
        return True
    finally:
        close_connection(conn)


def create_user(username: str, password: str) -> Optional[User]:
    """Create a new user. Returns the User or None if the username is taken."""
    hashed = generate_password_hash(password)
    try:
        conn = normalize_connection(get_connection())
        try:
            cur = conn.cursor()
            username = username.strip()

            if conn.is_sqlite:
                # SQLite: insert then fetch lastrowid
                safe_execute(
                    cur,
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, hashed),
                    conn,
                )
                new_id = cur.lastrowid
            else:
                # PostgreSQL: use RETURNING clause
                safe_execute(
                    cur,
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
                    (username, hashed),
                    conn,
                )
                result = cur.fetchone()
                new_id = result["id"]

            conn.commit()
            return User(id=new_id, username=username, password_hash=hashed)
        finally:
            close_connection(conn)
    except Exception as e:
        # Handle IntegrityError from both SQLite and PostgreSQL
        if isinstance(e, (sqlite3.IntegrityError, psycopg2.IntegrityError)):
            return None  # username already exists
        raise


def get_user_by_username(username: str) -> Optional[User]:
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        safe_execute(
            cur,
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username.strip(),),
            conn,
        )
        row = cur.fetchone()
    finally:
        close_connection(conn)
    if not row:
        return None
    return User(id=row["id"], username=row["username"], password_hash=row["password_hash"])


def get_user_by_id(user_id: int) -> Optional[User]:
    conn = normalize_connection(get_connection())
    try:
        cur = conn.cursor()
        safe_execute(
            cur,
            "SELECT id, username, password_hash FROM users WHERE id = %s",
            (user_id,),
            conn,
        )
        row = cur.fetchone()
    finally:
        close_connection(conn)
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

