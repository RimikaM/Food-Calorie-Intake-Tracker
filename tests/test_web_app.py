"""
Tests for web_app.py – Flask routes.
Uses Flask's test client; DB is patched to an in-memory SQLite instance.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from unittest.mock import patch

import pytest

import main as m
from web_app import app as flask_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def in_memory_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(m, "get_connection", lambda: conn)
    m.init_db()
    yield conn
    conn.close()


@pytest.fixture()
def client(in_memory_db):
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


@pytest.fixture()
def logged_in_client(client):
    """Register and log in a test user; return (client, user)."""
    client.post("/register", data={
        "username": "tester",
        "password": "testpass1",
        "confirm": "testpass1",
    })
    user = m.get_user_by_username("tester")
    return client, user


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_page_renders(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200
        assert b"Create" in resp.data

    def test_register_creates_user_and_redirects(self, client):
        resp = client.post("/register", data={
            "username": "alice", "password": "secure123", "confirm": "secure123",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert m.get_user_by_username("alice") is not None

    def test_register_duplicate_shows_error(self, client):
        m.create_user("alice", "secure123")
        resp = client.post("/register", data={
            "username": "alice", "password": "secure123", "confirm": "secure123",
        })
        assert b"taken" in resp.data

    def test_register_password_too_short(self, client):
        resp = client.post("/register", data={
            "username": "bob", "password": "abc", "confirm": "abc",
        })
        assert b"6 characters" in resp.data

    def test_register_password_mismatch(self, client):
        resp = client.post("/register", data={
            "username": "bob", "password": "secure123", "confirm": "different",
        })
        assert b"match" in resp.data


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_page_renders(self, client):
        assert client.get("/login").status_code == 200

    def test_login_valid_credentials_redirects(self, client):
        m.create_user("alice", "secure123")
        resp = client.post("/login", data={"username": "alice", "password": "secure123"})
        assert resp.status_code == 302

    def test_login_wrong_password_shows_error(self, client):
        m.create_user("alice", "secure123")
        resp = client.post("/login", data={"username": "alice", "password": "wrongpass"})
        assert b"Invalid" in resp.data

    def test_login_unknown_user_shows_error(self, client):
        resp = client.post("/login", data={"username": "nobody", "password": "pass"})
        assert b"Invalid" in resp.data

    def test_logout_redirects_to_login(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.get("/logout")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Protected routes redirect when not logged in
# ---------------------------------------------------------------------------

class TestAuthRequired:
    def test_index_requires_login(self, client):
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_history_requires_login(self, client):
        assert client.get("/history").status_code == 302

    def test_settings_requires_login(self, client):
        assert client.get("/settings").status_code == 302

    def test_entries_requires_login(self, client):
        assert client.get("/entries").status_code == 302

    def test_export_requires_login(self, client):
        assert client.get("/export").status_code == 302


# ---------------------------------------------------------------------------
# GET / (index)
# ---------------------------------------------------------------------------

class TestIndex:
    def test_index_renders(self, logged_in_client):
        client, _ = logged_in_client
        assert client.get("/").status_code == 200

    def test_index_shows_entries(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        today = date.today().isoformat()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today}T12:00", "Banana", 90),
        )
        resp = client.get("/")
        assert b"Banana" in resp.data
        assert b"90" in resp.data

    def test_index_shows_goal_progress(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        m.set_setting("calorie_goal", "2000", user_id=user.id)
        today = date.today().isoformat()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today}T12:00", "Lunch", 600),
        )
        resp = client.get("/")
        assert b"2000" in resp.data
        assert b"600" in resp.data

    def test_index_no_goal_no_progress_bar(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.get("/")
        assert b"border-radius:999px;height:7px" not in resp.data

    def test_index_shows_username_in_nav(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.get("/")
        assert b"tester" in resp.data


# ---------------------------------------------------------------------------
# POST /add
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_entry_redirects(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.post("/add", data={"food": "Rice", "calories": "200"})
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_add_entry_persists(self, logged_in_client):
        client, user = logged_in_client
        client.post("/add", data={"food": "Rice", "calories": "200", "notes": "brown"})
        entries = m.fetch_entries_for_date(date.today(), user_id=user.id)
        assert len(entries) == 1
        assert entries[0].food == "Rice"
        assert entries[0].calories == 200
        assert entries[0].notes == "brown"

    def test_add_entry_isolated_to_user(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        other = m.create_user("other_add", "otherpass1")
        client.post("/add", data={"food": "Rice", "calories": "200"})
        assert m.fetch_entries_for_date(date.today(), user_id=other.id) == []

    def test_add_with_empty_food_redirects(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.post("/add", data={"food": "", "calories": "200"})
        assert resp.status_code == 302

    def test_add_with_invalid_calories_redirects(self, logged_in_client):
        client, user = logged_in_client
        resp = client.post("/add", data={"food": "Rice", "calories": "abc"})
        assert resp.status_code == 302
        assert m.fetch_entries_for_date(date.today(), user_id=user.id) == []


# ---------------------------------------------------------------------------
# GET /day/<day_str>
# ---------------------------------------------------------------------------

class TestDayView:
    def test_day_view_renders(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        today = date.today().isoformat()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today}T09:00", "Oatmeal", 300),
        )
        resp = client.get(f"/day/{today}")
        assert resp.status_code == 200
        assert b"Oatmeal" in resp.data

    def test_day_view_invalid_date_redirects(self, logged_in_client):
        client, _ = logged_in_client
        assert client.get("/day/not-a-date").status_code == 302

    def test_day_view_empty_day(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.get(f"/day/{date.today().isoformat()}")
        assert b"No entries" in resp.data


# ---------------------------------------------------------------------------
# GET /history
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_renders(self, logged_in_client):
        client, _ = logged_in_client
        assert client.get("/history").status_code == 200

    def test_history_shows_days(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        today = date.today().isoformat()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today}T10:00", "Food", 500),
        )
        resp = client.get("/history")
        assert today.encode() in resp.data

    def test_history_isolated_between_users(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        other = m.create_user("other_hist", "otherpass1")
        today = date.today().isoformat()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (other.id, f"{today}T10:00", "OtherFood", 999),
        )
        rows = m.fetch_recent_days(user_id=user.id)
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Food search / select / log
# ---------------------------------------------------------------------------

class TestFoodsSearch:
    def test_search_get_renders(self, logged_in_client):
        client, _ = logged_in_client
        assert client.get("/foods/search").status_code == 200

    def test_search_post_no_api_key(self, logged_in_client, monkeypatch):
        client, _ = logged_in_client
        monkeypatch.delenv("USDA_FDC_API_KEY", raising=False)
        resp = client.post("/foods/search", data={"query": "apple"})
        assert b"USDA_FDC_API_KEY" in resp.data

    def test_search_post_shows_results(self, logged_in_client, monkeypatch):
        client, _ = logged_in_client
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        from usda_api import UsdaFood, UsdaSearchResponse
        fake = UsdaSearchResponse(
            foods=[UsdaFood(fdc_id=1, description="Apple, raw", brand=None,
                            calories=52.0, protein_g=0.3, carbs_g=14.0, fat_g=0.2)],
            status_code=200,
        )
        with patch("web_app.search_foods", return_value=fake):
            resp = client.post("/foods/search", data={"query": "apple"})
        assert b"Apple, raw" in resp.data


class TestFoodsSelect:
    def test_select_creates_food_and_redirects(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.post("/foods/select", data={
            "fdc_id": "9001", "description": "Salmon", "brand": "Wild",
            "calories": "208", "protein_g": "20", "carbs_g": "0", "fat_g": "13",
        })
        assert resp.status_code == 302
        assert "/foods/log/" in resp.headers["Location"]

    def test_select_invalid_fdc_id_redirects(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.post("/foods/select", data={"fdc_id": "bad"})
        assert "/foods/search" in resp.headers["Location"]


class TestFoodsLog:
    def _create_food(self):
        return m.get_or_create_food(
            fdc_id=42, description="Egg", brand=None,
            calories=78.0, protein_g=6.0, carbs_g=0.6, fat_g=5.0,
        )

    def test_log_get_renders(self, logged_in_client):
        client, _ = logged_in_client
        food = self._create_food()
        resp = client.get(f"/foods/log/{food.id}")
        assert b"Egg" in resp.data

    def test_log_get_missing_food_redirects(self, logged_in_client):
        client, _ = logged_in_client
        assert client.get("/foods/log/9999").status_code == 302

    def test_log_post_saves_scaled_macros(self, logged_in_client):
        client, user = logged_in_client
        food = self._create_food()
        client.post(f"/foods/log/{food.id}", data={"servings": "2", "meal": "breakfast"})
        entries = m.fetch_entries_for_date(date.today(), user_id=user.id)
        assert entries[0].calories == 156  # 78 * 2
        assert entries[0].protein_g == pytest.approx(12.0)
        assert entries[0].meal == "breakfast"

    def test_log_post_missing_food_redirects(self, logged_in_client):
        client, _ = logged_in_client
        assert client.post("/foods/log/9999", data={"servings": "1"}).status_code == 302

    def test_log_post_invalid_servings_defaults_to_1(self, logged_in_client):
        client, user = logged_in_client
        food = self._create_food()
        client.post(f"/foods/log/{food.id}", data={"servings": "bad"})
        assert m.fetch_entries_for_date(date.today(), user_id=user.id)[0].calories == 78


# ---------------------------------------------------------------------------
# /entries
# ---------------------------------------------------------------------------

class TestEntriesView:
    def test_entries_renders(self, logged_in_client):
        client, _ = logged_in_client
        assert client.get("/entries").status_code == 200

    def test_entries_shows_only_current_user(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        other = m.create_user("other_ent", "otherpass2")
        today = date.today().isoformat()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today}T10:00", "MyFood", 100),
        )
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (other.id, f"{today}T10:00", "OtherFood", 200),
        )
        resp = client.get("/entries")
        assert b"MyFood" in resp.data
        assert b"OtherFood" not in resp.data


# ---------------------------------------------------------------------------
# /export
# ---------------------------------------------------------------------------

class TestExportCsv:
    def test_export_returns_csv(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{date.today().isoformat()}T10:00", "Toast", 150),
        )
        resp = client.get("/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        assert b"Toast" in resp.data
        assert b"id,eaten_at,food,calories" in resp.data

    def test_export_empty_has_header_only(self, logged_in_client):
        client, _ = logged_in_client
        resp = client.get("/export")
        lines = resp.data.decode().strip().splitlines()
        assert len(lines) == 1

    def test_export_only_current_user_data(self, logged_in_client, in_memory_db):
        client, user = logged_in_client
        other = m.create_user("other_exp", "otherpass3")
        today = date.today().isoformat()
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (user.id, f"{today}T10:00", "MyExport", 100),
        )
        in_memory_db.execute(
            "INSERT INTO entries (user_id, eaten_at, food, calories) VALUES (?, ?, ?, ?)",
            (other.id, f"{today}T10:00", "NotMine", 200),
        )
        resp = client.get("/export")
        assert b"MyExport" in resp.data
        assert b"NotMine" not in resp.data


# ---------------------------------------------------------------------------
# /settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_settings_get_renders(self, logged_in_client):
        client, _ = logged_in_client
        assert client.get("/settings").status_code == 200

    def test_settings_shows_current_goal(self, logged_in_client):
        client, user = logged_in_client
        m.set_setting("calorie_goal", "1800", user_id=user.id)
        resp = client.get("/settings")
        assert b"1800" in resp.data

    def test_settings_post_saves_goal(self, logged_in_client):
        client, user = logged_in_client
        resp = client.post("/settings", data={"calorie_goal": "2200"})
        assert resp.status_code == 200
        assert b"saved" in resp.data.lower()
        assert m.get_calorie_goal(user_id=user.id) == 2200

    def test_settings_post_invalid_value_ignored(self, logged_in_client):
        client, user = logged_in_client
        client.post("/settings", data={"calorie_goal": "abc"})
        assert m.get_calorie_goal(user_id=user.id) is None

    def test_settings_post_updates_existing_goal(self, logged_in_client):
        client, user = logged_in_client
        m.set_setting("calorie_goal", "2000", user_id=user.id)
        client.post("/settings", data={"calorie_goal": "2500"})
        assert m.get_calorie_goal(user_id=user.id) == 2500

    def test_settings_isolated_between_users(self, logged_in_client):
        client, user = logged_in_client
        other = m.create_user("other_cfg", "otherpass4")
        client.post("/settings", data={"calorie_goal": "1800"})
        assert m.get_calorie_goal(user_id=other.id) is None
