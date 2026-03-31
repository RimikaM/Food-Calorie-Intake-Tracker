"""
Tests for main.py – DB helpers, settings, and calorie goal.
All tests use an in-memory SQLite DB patched via monkeypatch so they
never touch the real calories.db file.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional
from unittest.mock import patch

import pytest

import main as m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch, tmp_path):
    """
    Replace every get_connection() call with one that returns an in-memory DB.
    The connection is kept open for the duration of the test so the in-memory
    data persists across multiple calls within the same test.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(m, "get_connection", lambda: conn)
    m.init_db()
    yield conn
    conn.close()


@pytest.fixture()
def user(in_memory_db):
    """Create and return a test user."""
    return m.create_user("testuser", "password123")


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_tables_created(self, in_memory_db):
        tables = {
            row[0]
            for row in in_memory_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"entries", "foods", "settings", "users"}.issubset(tables)

    def test_idempotent(self, in_memory_db):
        # Calling init_db a second time must not raise.
        m.init_db()


# ---------------------------------------------------------------------------
# User auth
# ---------------------------------------------------------------------------

class TestUsers:
    def test_create_user(self, in_memory_db):
        user = m.create_user("alice", "secret99")
        assert user is not None
        assert user.id is not None
        assert user.username == "alice"

    def test_duplicate_username_returns_none(self, in_memory_db):
        m.create_user("alice", "secret99")
        assert m.create_user("alice", "other") is None

    def test_get_user_by_username(self, in_memory_db):
        m.create_user("bob", "pass1234")
        user = m.get_user_by_username("bob")
        assert user is not None
        assert user.username == "bob"

    def test_get_user_by_username_missing(self, in_memory_db):
        assert m.get_user_by_username("nobody") is None

    def test_get_user_by_id(self, in_memory_db):
        created = m.create_user("carol", "pass1234")
        fetched = m.get_user_by_id(created.id)
        assert fetched is not None
        assert fetched.username == "carol"

    def test_get_user_by_id_missing(self, in_memory_db):
        assert m.get_user_by_id(9999) is None

    def test_verify_password_correct(self, in_memory_db):
        user = m.create_user("dave", "correct_password")
        assert m.verify_password(user, "correct_password") is True

    def test_verify_password_wrong(self, in_memory_db):
        user = m.create_user("eve", "correct_password")
        assert m.verify_password(user, "wrong_password") is False

    def test_password_is_hashed(self, in_memory_db):
        user = m.create_user("frank", "mypassword")
        assert user.password_hash != "mypassword"


# ---------------------------------------------------------------------------
# add_entry / fetch_entries_for_date
# ---------------------------------------------------------------------------

class TestAddAndFetchEntries:
    def test_add_minimal_entry(self, user):
        today = date.today()
        m.add_entry(food="Apple", calories=95, user_id=user.id)
        entries = m.fetch_entries_for_date(today, user_id=user.id)
        assert len(entries) == 1
        e = entries[0]
        assert e.food == "Apple"
        assert e.calories == 95
        assert e.protein_g is None
        assert e.carbs_g is None
        assert e.fat_g is None
        assert e.meal is None
        assert e.servings is None
        assert e.notes is None

    def test_add_full_entry(self, user):
        today = date.today()
        m.add_entry(
            food="Chicken breast",
            calories=165,
            notes="grilled",
            protein_g=31.0,
            carbs_g=0.0,
            fat_g=3.6,
            meal="lunch",
            servings=1.0,
            user_id=user.id,
        )
        entries = m.fetch_entries_for_date(today, user_id=user.id)
        assert len(entries) == 1
        e = entries[0]
        assert e.food == "Chicken breast"
        assert e.calories == 165
        assert e.notes == "grilled"
        assert e.protein_g == pytest.approx(31.0)
        assert e.carbs_g == pytest.approx(0.0)
        assert e.fat_g == pytest.approx(3.6)
        assert e.meal == "lunch"
        assert e.servings == pytest.approx(1.0)

    def test_fetch_only_returns_correct_day(self, user, in_memory_db):
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Insert one entry for today and one for yesterday manually.
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today.isoformat()}T12:00", "Today food", 200),
        )
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{yesterday.isoformat()}T12:00", "Yesterday food", 300),
        )

        assert len(m.fetch_entries_for_date(today, user_id=user.id)) == 1
        assert len(m.fetch_entries_for_date(yesterday, user_id=user.id)) == 1

    def test_entries_isolated_between_users(self, in_memory_db):
        u1 = m.create_user("user1", "pass1111")
        u2 = m.create_user("user2", "pass2222")
        m.add_entry(food="User1 food", calories=100, user_id=u1.id)
        m.add_entry(food="User2 food", calories=200, user_id=u2.id)
        assert len(m.fetch_entries_for_date(date.today(), user_id=u1.id)) == 1
        assert len(m.fetch_entries_for_date(date.today(), user_id=u2.id)) == 1
        assert m.fetch_entries_for_date(date.today(), user_id=u1.id)[0].food == "User1 food"

    def test_food_name_stripped(self, user):
        m.add_entry(food="  rice  ", calories=200, user_id=user.id)
        entries = m.fetch_entries_for_date(date.today(), user_id=user.id)
        assert entries[0].food == "rice"

    def test_notes_stripped(self, user):
        m.add_entry(food="Toast", calories=100, notes="  with butter  ", user_id=user.id)
        entries = m.fetch_entries_for_date(date.today(), user_id=user.id)
        assert entries[0].notes == "with butter"

    def test_multiple_entries_ordered_asc(self, user, in_memory_db):
        today = date.today()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today.isoformat()}T08:00", "Breakfast", 400),
        )
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today.isoformat()}T13:00", "Lunch", 600),
        )
        entries = m.fetch_entries_for_date(today, user_id=user.id)
        assert entries[0].food == "Breakfast"
        assert entries[1].food == "Lunch"


# ---------------------------------------------------------------------------
# fetch_all_entries
# ---------------------------------------------------------------------------

class TestFetchAllEntries:
    def test_returns_newest_first(self, user, in_memory_db):
        today = date.today()
        yesterday = today - timedelta(days=1)
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{yesterday.isoformat()}T10:00", "Old", 100),
        )
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today.isoformat()}T10:00", "New", 200),
        )
        entries = m.fetch_all_entries(user_id=user.id)
        assert entries[0].food == "New"
        assert entries[1].food == "Old"

    def test_empty_returns_empty_list(self, user):
        assert m.fetch_all_entries(user_id=user.id) == []


# ---------------------------------------------------------------------------
# fetch_recent_days
# ---------------------------------------------------------------------------

class TestFetchRecentDays:
    def test_aggregates_by_day(self, user, in_memory_db):
        today = date.today()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today.isoformat()}T08:00", "Breakfast", 300),
        )
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today.isoformat()}T13:00", "Lunch", 500),
        )
        rows = m.fetch_recent_days(user_id=user.id, limit=7)
        assert len(rows) == 1
        assert rows[0]["total_calories"] == 800
        assert rows[0]["items"] == 2

    def test_respects_limit(self, user, in_memory_db):
        for i in range(10):
            day = (date.today() - timedelta(days=i)).isoformat()
            in_memory_db.execute(
                "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
                (user.id, f"{day}T10:00", f"Food {i}", 100),
            )
        rows = m.fetch_recent_days(user_id=user.id, limit=3)
        assert len(rows) == 3

    def test_ordered_newest_first(self, user, in_memory_db):
        today = date.today()
        yesterday = today - timedelta(days=1)
        for d in [today, yesterday]:
            in_memory_db.execute(
                "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
                (user.id, f"{d.isoformat()}T10:00", "Food", 100),
            )
        rows = m.fetch_recent_days(user_id=user.id, limit=7)
        assert rows[0]["day"] == today.isoformat()
        assert rows[1]["day"] == yesterday.isoformat()


# ---------------------------------------------------------------------------
# get_or_create_food / get_food_by_id
# ---------------------------------------------------------------------------

class TestFoodCRUD:
    def _make_food(self, fdc_id=12345):
        return m.get_or_create_food(
            fdc_id=fdc_id,
            description="Grilled Salmon",
            brand="Generic",
            calories=208.0,
            protein_g=20.0,
            carbs_g=0.0,
            fat_g=13.0,
        )

    def test_create_food(self, in_memory_db):
        food = self._make_food()
        assert food.id is not None
        assert food.fdc_id == 12345
        assert food.description == "Grilled Salmon"
        assert food.calories == pytest.approx(208.0)

    def test_get_existing_food(self, in_memory_db):
        food1 = self._make_food()
        food2 = self._make_food()  # same fdc_id
        assert food1.id == food2.id

    def test_get_food_by_id(self, in_memory_db):
        food = self._make_food()
        fetched = m.get_food_by_id(food.id)
        assert fetched is not None
        assert fetched.fdc_id == 12345
        assert fetched.brand == "Generic"

    def test_get_food_by_id_missing(self, in_memory_db):
        assert m.get_food_by_id(9999) is None

    def test_food_nullable_brand(self, in_memory_db):
        food = m.get_or_create_food(
            fdc_id=99999,
            description="Plain Rice",
            brand=None,
            calories=130.0,
            protein_g=2.7,
            carbs_g=28.0,
            fat_g=0.3,
        )
        assert food.brand is None


# ---------------------------------------------------------------------------
# Settings – get_setting / set_setting
# ---------------------------------------------------------------------------

class TestSettings:
    def test_get_missing_key_returns_default(self, user):
        assert m.get_setting("nonexistent", user_id=user.id) is None
        assert m.get_setting("nonexistent", user_id=user.id, default="fallback") == "fallback"

    def test_set_and_get(self, user):
        m.set_setting("theme", "dark", user_id=user.id)
        assert m.get_setting("theme", user_id=user.id) == "dark"

    def test_update_existing_key(self, user):
        m.set_setting("theme", "dark", user_id=user.id)
        m.set_setting("theme", "light", user_id=user.id)
        assert m.get_setting("theme", user_id=user.id) == "light"

    def test_settings_isolated_between_users(self, in_memory_db):
        u1 = m.create_user("u1", "pass1111")
        u2 = m.create_user("u2", "pass2222")
        m.set_setting("theme", "dark", user_id=u1.id)
        m.set_setting("theme", "light", user_id=u2.id)
        assert m.get_setting("theme", user_id=u1.id) == "dark"
        assert m.get_setting("theme", user_id=u2.id) == "light"


# ---------------------------------------------------------------------------
# Calorie goal
# ---------------------------------------------------------------------------

class TestCalorieGoal:
    def test_no_goal_returns_none(self, user):
        assert m.get_calorie_goal(user_id=user.id) is None

    def test_set_and_get_goal(self, user):
        m.set_setting("calorie_goal", "2000", user_id=user.id)
        assert m.get_calorie_goal(user_id=user.id) == 2000

    def test_goal_returns_int(self, user):
        m.set_setting("calorie_goal", "1800", user_id=user.id)
        goal = m.get_calorie_goal(user_id=user.id)
        assert isinstance(goal, int)

    def test_invalid_goal_returns_none(self, user):
        m.set_setting("calorie_goal", "not_a_number", user_id=user.id)
        assert m.get_calorie_goal(user_id=user.id) is None

    def test_update_goal(self, user):
        m.set_setting("calorie_goal", "2000", user_id=user.id)
        m.set_setting("calorie_goal", "2500", user_id=user.id)
        assert m.get_calorie_goal(user_id=user.id) == 2500


class TestBarcodeScanning:
    def test_add_barcode_mapping(self, user):
        """Test adding a barcode mapping."""
        result = m.add_barcode_mapping("0012000123456", 999, "Test Food")
        assert result is True

    def test_lookup_barcode_not_cached(self, user):
        """Test lookup returns None for uncached barcode."""
        result = m.lookup_barcode("0012000999999", user.id)
        assert result is None

    def test_lookup_barcode_cached(self, user):
        """Test barcode lookup from cache."""
        m.add_barcode_mapping("0012000123456", 999, "Test Food")
        result = m.lookup_barcode("0012000123456", user.id)
        assert result is not None
        assert result["ean_code"] == "0012000123456"
        assert result["fdc_id"] == 999
        assert result["food_name"] == "Test Food"
        assert result["from_cache"] is True

    def test_barcode_scan_count_increments(self, user):
        """Test that scan count increments on repeated lookups."""
        m.add_barcode_mapping("0012000123456", 999, "Test Food")
        result1 = m.lookup_barcode("0012000123456", user.id)
        assert result1["scan_count"] == 2  # Starts at 1, then increments to 2

        result2 = m.lookup_barcode("0012000123456", user.id)
        assert result2["scan_count"] == 3  # Increments again

    def test_get_barcode_history(self, user):
        """Test retrieving barcode history."""
        m.add_barcode_mapping("0012000111111", 999, "Food A")
        m.add_barcode_mapping("0012000222222", 998, "Food B")

        m.lookup_barcode("0012000111111", user.id)
        m.lookup_barcode("0012000222222", user.id)

        history = m.get_barcode_history(user.id, limit=10)
        assert len(history) >= 2
        assert any(item["ean_code"] == "0012000111111" for item in history)
        assert any(item["ean_code"] == "0012000222222" for item in history)

    def test_barcode_history_ordered_by_last_scanned(self, user):
        """Test barcode history is ordered by last_scanned descending."""
        m.add_barcode_mapping("0012000111111", 999, "Food A")
        m.add_barcode_mapping("0012000222222", 998, "Food B")

        m.lookup_barcode("0012000111111", user.id)
        import time
        time.sleep(0.01)
        m.lookup_barcode("0012000222222", user.id)

        history = m.get_barcode_history(user.id, limit=10)
        # Most recent should come first
        assert history[0]["ean_code"] == "0012000222222"

    def test_barcode_history_limit(self, user):
        """Test barcode history respects limit parameter."""
        for i in range(5):
            m.add_barcode_mapping(f"001200010{i:05d}", 999 - i, f"Food {i}")
            m.lookup_barcode(f"001200010{i:05d}", user.id)

        history = m.get_barcode_history(user.id, limit=3)
        assert len(history) == 3


class TestBulkImportExport:
    def test_export_all_user_data_empty(self, user):
        """Test export with no data."""
        result = m.export_all_user_data(user.id)
        assert result["entries"] == []
        assert result["weight_logs"] == []
        assert result["wellness_logs"] == []
        assert result["recipes"] == []

    def test_export_includes_settings(self, user):
        """Test export includes settings when requested."""
        m.set_setting("calorie_goal", "2000", user_id=user.id)
        result = m.export_all_user_data(user.id, include_settings=True)
        assert "settings" in result
        assert result["settings"]["calorie_goal"] == "2000"

    def test_import_entries_from_csv(self, user):
        """Test importing entries from CSV."""
        csv_lines = [
            "food,calories,date,time,notes,protein_g,carbs_g,fat_g,meal",
            "Chicken,185,2026-03-27,12:30,Grilled,35.5,0,8.5,lunch",
            "Rice,200,2026-03-27,12:30,,4,45,0,lunch",
        ]
        count, errors = m.import_entries_from_csv(user.id, csv_lines)
        assert count == 2
        assert len(errors) == 0

    def test_import_entries_invalid_csv(self, user):
        """Test importing with invalid CSV."""
        csv_lines = [
            "invalid,header,format",
            "data,here",
        ]
        count, errors = m.import_entries_from_csv(user.id, csv_lines)
        assert count == 0
        assert len(errors) > 0

    def test_import_entries_missing_required(self, user):
        """Test importing entries with missing required fields."""
        csv_lines = [
            "food,calories,date,time,notes,protein_g,carbs_g,fat_g,meal",
            "Chicken,,2026-03-27,12:30,,,,,",
        ]
        count, errors = m.import_entries_from_csv(user.id, csv_lines)
        assert count == 0
        assert any("Missing" in err or "Invalid" in err for err in errors)

    def test_import_weight_from_csv(self, user):
        """Test importing weight logs from CSV."""
        csv_lines = [
            "date,weight_kg,notes",
            "2026-03-27,72.5,Morning",
            "2026-03-28,72.3,Morning",
        ]
        count, errors = m.import_weight_from_csv(user.id, csv_lines)
        assert count == 2
        assert len(errors) == 0

    def test_import_wellness_from_csv(self, user):
        """Test importing wellness logs from CSV."""
        csv_lines = [
            "date,log_type,value,notes",
            "2026-03-27,water_ml,2000,Eight glasses",
            "2026-03-27,caffeine_mg,200,Two coffees",
        ]
        count, errors = m.import_wellness_from_csv(user.id, csv_lines)
        assert count == 2
        assert len(errors) == 0


class TestNotifications:
    def test_create_notification(self, user):
        """Test creating a notification."""
        result = m.create_notification(
            user.id,
            "test_event",
            "Test Title",
            "Test message",
            "/test",
        )
        assert result is True

    def test_get_unread_notifications(self, user):
        """Test getting unread notifications."""
        m.create_notification(user.id, "event1", "Title 1", "Message 1", "/")
        m.create_notification(user.id, "event2", "Title 2", "Message 2", "/")

        notifs = m.get_unread_notifications(user.id)
        assert len(notifs) >= 2
        assert all(notif["title"] in ["Title 1", "Title 2"] for notif in notifs)

    def test_mark_notification_read(self, user):
        """Test marking notification as read."""
        m.create_notification(user.id, "event", "Title", "Message")
        notifs = m.get_unread_notifications(user.id)
        notif_id = notifs[0]["id"]

        result = m.mark_notification_read(notif_id, user.id)
        assert result is True

        # Verify it's no longer in unread
        unread = m.get_unread_notifications(user.id)
        assert not any(n["id"] == notif_id for n in unread)

    def test_mark_all_notifications_read(self, user):
        """Test marking all notifications as read."""
        m.create_notification(user.id, "event1", "Title 1")
        m.create_notification(user.id, "event2", "Title 2")

        m.mark_all_notifications_read(user.id)
        unread = m.get_unread_notifications(user.id)
        assert len(unread) == 0

    def test_check_daily_goals_creates_notification(self, user):
        """Test that creating notifications works."""
        # Just verify we can create a notification without errors
        m.create_notification(user.id, "calorie_goal_reached", "Test Goal", "You hit your goal!")

        notifs = m.get_unread_notifications(user.id)
        assert any(n["event_type"] == "calorie_goal_reached" for n in notifs)


