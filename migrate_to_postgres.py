#!/usr/bin/env python3
"""
Migrate data from SQLite to PostgreSQL
"""
import os
import sqlite3
import psycopg2
from pathlib import Path

# SQLite connection
sqlite_path = Path(__file__).with_name("calories.db")
sqlite_conn = sqlite3.connect(sqlite_path)
sqlite_conn.row_factory = sqlite3.Row

# PostgreSQL connection (customize using env vars if needed)
pg_host = os.getenv("PGHOST", "localhost")
pg_port = int(os.getenv("PGPORT", "5432"))
pg_db = os.getenv("PGDATABASE", "food_calorie_intake")
pg_user = os.getenv("PGUSER", "food_calorie_user")
pg_password = os.getenv("PGPASSWORD", "")

postgres_conn = psycopg2.connect(
    host=pg_host,
    port=pg_port,
    database=pg_db,
    user=pg_user,
    password=pg_password,
)
postgres_cursor = postgres_conn.cursor()

# Get all table names
sqlite_cursor = sqlite_conn.cursor()
sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in sqlite_cursor.fetchall()]

print(f"Found tables: {tables}")

for table in tables:
    print(f"\nMigrating {table}...")

    # Get schema
    sqlite_cursor.execute(f"PRAGMA table_info({table})")
    columns_info = sqlite_cursor.fetchall()
    columns = [col[1] for col in columns_info]

    # Fetch all data
    sqlite_cursor.execute(f"SELECT * FROM {table}")
    rows = sqlite_cursor.fetchall()

    if not rows:
        print(f"  {table} is empty, skipping")
        continue

    # Insert into PostgreSQL
    placeholders = ",".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    for row in rows:
        try:
            postgres_cursor.execute(insert_sql, tuple(row))
        except Exception as e:
            print(f"  Error inserting row: {e}")

    postgres_conn.commit()
    print(f"  ✓ Migrated {len(rows)} rows")

# Rebuild indexes
print("\nRebuilding indexes...")
postgres_cursor.execute(f"REINDEX DATABASE {pg_db}")
postgres_conn.commit()
print("✓ Indexes rebuilt")

sqlite_conn.close()
postgres_conn.close()

print("\n✓ Migration complete!")
print(f"Next: Set DATABASE_URL=postgresql://{pg_user}:<password>@{pg_host}:{pg_port}/{pg_db}")
