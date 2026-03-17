"""
Tests for usda_api.py – macro extraction and search_foods().
Network calls are fully mocked so no real HTTP requests are made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from usda_api import UsdaFood, UsdaSearchResponse, _extract_macros, search_foods


# ---------------------------------------------------------------------------
# _extract_macros
# ---------------------------------------------------------------------------

class TestExtractMacros:
    def _nutrient(self, nutrient_id, name, value):
        return {"nutrientId": nutrient_id, "nutrientName": name, "value": value}

    def test_all_macros_by_id(self):
        nutrients = [
            self._nutrient(1008, "Energy", 200),
            self._nutrient(1003, "Protein", 25.0),
            self._nutrient(1005, "Carbohydrate, by difference", 10.0),
            self._nutrient(1004, "Total lipid (fat)", 8.0),
        ]
        cals, protein, carbs, fat = _extract_macros(nutrients)
        assert cals == pytest.approx(200)
        assert protein == pytest.approx(25.0)
        assert carbs == pytest.approx(10.0)
        assert fat == pytest.approx(8.0)

    def test_legacy_ids(self):
        nutrients = [
            {"nutrientId": 208, "nutrientName": "Energy", "value": 100},
            {"nutrientId": 203, "nutrientName": "Protein", "value": 5},
            {"nutrientId": 205, "nutrientName": "Carbohydrate, by difference", "value": 15},
            {"nutrientId": 204, "nutrientName": "Total Fat", "value": 3},
        ]
        cals, protein, carbs, fat = _extract_macros(nutrients)
        assert cals == pytest.approx(100)
        assert protein == pytest.approx(5)
        assert carbs == pytest.approx(15)
        assert fat == pytest.approx(3)

    def test_macros_by_name(self):
        nutrients = [
            {"nutrientId": None, "nutrientName": "Energy (Atwater General Factors)", "value": 150},
            {"nutrientId": None, "nutrientName": "Protein", "value": 12},
            {"nutrientId": None, "nutrientName": "Carbohydrate, by difference", "value": 20},
            {"nutrientId": None, "nutrientName": "Total lipid (fat)", "value": 5},
        ]
        cals, protein, carbs, fat = _extract_macros(nutrients)
        assert cals == pytest.approx(150)
        assert protein == pytest.approx(12)
        assert carbs == pytest.approx(20)
        assert fat == pytest.approx(5)

    def test_saturated_fat_ignored_for_fat(self):
        nutrients = [
            {"nutrientId": None, "nutrientName": "Fatty acids, total saturated", "value": 4},
            {"nutrientId": 1004, "nutrientName": "Total lipid (fat)", "value": 10},
        ]
        _, _, _, fat = _extract_macros(nutrients)
        assert fat == pytest.approx(10)

    def test_empty_list_returns_all_none(self):
        assert _extract_macros([]) == (None, None, None, None)

    def test_none_input_returns_all_none(self):
        assert _extract_macros(None) == (None, None, None, None)

    def test_invalid_value_skipped(self):
        nutrients = [
            {"nutrientId": 1008, "nutrientName": "Energy", "value": "not_a_number"},
            {"nutrientId": 1003, "nutrientName": "Protein", "value": 10},
        ]
        cals, protein, _, _ = _extract_macros(nutrients)
        assert cals is None
        assert protein == pytest.approx(10)

    def test_first_value_wins(self):
        """When the same macro appears twice, the first value is kept."""
        nutrients = [
            {"nutrientId": 1008, "nutrientName": "Energy", "value": 100},
            {"nutrientId": 1008, "nutrientName": "Energy", "value": 999},
        ]
        cals, _, _, _ = _extract_macros(nutrients)
        assert cals == pytest.approx(100)


# ---------------------------------------------------------------------------
# search_foods
# ---------------------------------------------------------------------------

class TestSearchFoods:
    def _mock_response(self, status=200, json_data=None, text=""):
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = json_data or {}
        resp.text = text
        return resp

    def _sample_payload(self):
        return {
            "foods": [
                {
                    "fdcId": 111,
                    "description": "Apple, raw",
                    "brandOwner": None,
                    "brandName": None,
                    "foodNutrients": [
                        {"nutrientId": 1008, "nutrientName": "Energy", "value": 52},
                        {"nutrientId": 1003, "nutrientName": "Protein", "value": 0.3},
                        {"nutrientId": 1005, "nutrientName": "Carbohydrate, by difference", "value": 14},
                        {"nutrientId": 1004, "nutrientName": "Total lipid (fat)", "value": 0.2},
                    ],
                }
            ]
        }

    def test_missing_api_key_returns_error(self, monkeypatch):
        monkeypatch.delenv("USDA_FDC_API_KEY", raising=False)
        r = search_foods("apple")
        assert r.error is not None
        assert "USDA_FDC_API_KEY" in r.error
        assert r.foods == []

    def test_empty_query_returns_empty(self, monkeypatch):
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        r = search_foods("   ")
        assert r.foods == []
        assert r.error is None

    def test_successful_search(self, monkeypatch):
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        with patch("usda_api.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(200, self._sample_payload())
            r = search_foods("apple")

        assert r.error is None
        assert len(r.foods) == 1
        f = r.foods[0]
        assert f.fdc_id == 111
        assert f.description == "Apple, raw"
        assert f.calories == pytest.approx(52)
        assert f.protein_g == pytest.approx(0.3)
        assert f.carbs_g == pytest.approx(14)
        assert f.fat_g == pytest.approx(0.2)

    def test_http_error_returns_error(self, monkeypatch):
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        with patch("usda_api.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(403, text="Forbidden")
            r = search_foods("apple")

        assert r.foods == []
        assert "403" in r.error
        assert r.status_code == 403

    def test_network_error_returns_error(self, monkeypatch):
        import requests as req_lib
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        with patch("usda_api.requests.get", side_effect=req_lib.RequestException("timeout")):
            r = search_foods("apple")

        assert r.foods == []
        assert "Network error" in r.error

    def test_food_without_fdc_id_skipped(self, monkeypatch):
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        payload = {
            "foods": [
                {"fdcId": None, "description": "Ghost food", "foodNutrients": []},
                {"fdcId": 222, "description": "Real food", "foodNutrients": []},
            ]
        }
        with patch("usda_api.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(200, payload)
            r = search_foods("food")

        assert len(r.foods) == 1
        assert r.foods[0].fdc_id == 222

    def test_brand_owner_preferred_over_brand_name(self, monkeypatch):
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        payload = {
            "foods": [
                {
                    "fdcId": 333,
                    "description": "Cereal",
                    "brandOwner": "Kellogg's",
                    "brandName": "Other Brand",
                    "foodNutrients": [],
                }
            ]
        }
        with patch("usda_api.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(200, payload)
            r = search_foods("cereal")

        assert r.foods[0].brand == "Kellogg's"

    def test_no_foods_key_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        with patch("usda_api.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(200, {})
            r = search_foods("xyz")

        assert r.foods == []
        assert r.error is None

    def test_page_size_passed_to_request(self, monkeypatch):
        monkeypatch.setenv("USDA_FDC_API_KEY", "testkey")
        with patch("usda_api.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(200, {"foods": []})
            search_foods("chicken", page_size=5)

        _, kwargs = mock_get.call_args
        assert kwargs["params"]["pageSize"] == 5
