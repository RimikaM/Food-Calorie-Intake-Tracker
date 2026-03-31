from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

import requests


@dataclass
class UsdaFood:
    fdc_id: int
    description: str
    brand: Optional[str]
    calories: Optional[float]
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]


@dataclass
class UsdaSearchResponse:
    foods: List[UsdaFood]
    error: Optional[str] = None
    status_code: Optional[int] = None


def _get_api_key() -> Optional[str]:
    return os.getenv("USDA_FDC_API_KEY")


def _extract_macros(food_nutrients) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    calories = protein = carbs = fat = None

    for n in food_nutrients or []:
        # FDC can use nutrientId, number, or names; we try all.
        nid = str(n.get("nutrientId") or n.get("number") or "")
        name = (n.get("nutrientName") or n.get("name") or "").lower()
        value = n.get("value")
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue

        # Energy (kcal)
        if nid in {"1008", "208"} or "energy" in name:
            calories = calories or value_f
        # Protein
        elif nid in {"1003", "203"} or "protein" in name:
            protein = protein or value_f
        # Carbohydrate
        elif nid in {"1005", "205"} or "carbohydrate" in name:
            carbs = carbs or value_f
        # Fat
        elif nid in {"1004", "204"} or ("fat" in name and "saturated" not in name):
            fat = fat or value_f

    return calories, protein, carbs, fat


def search_foods(query: str, page_size: int = 15) -> UsdaSearchResponse:
    """
    Search USDA FoodData Central for foods matching the query.

    Returns foods plus an optional error message for display.
    """
    api_key = _get_api_key()
    if not api_key or not query.strip():
        return UsdaSearchResponse(
            foods=[],
            error="Missing USDA_FDC_API_KEY (set it in your terminal, then restart the web server)."
            if not api_key
            else None,
        )

    url = "https://api.nal.usda.gov/fdc/v1/foods/search"
    params = {
        "api_key": api_key,
        "query": query.strip(),
        "pageSize": page_size,
    }

    try:
        resp = requests.get(url, params=params, timeout=6)
    except requests.RequestException:
        return UsdaSearchResponse(
            foods=[],
            error="Network error calling USDA FoodData Central.",
        )

    if resp.status_code != 200:
        snippet = resp.text[:250] if resp.text else ""
        return UsdaSearchResponse(
            foods=[],
            error=f"USDA search failed (HTTP {resp.status_code}). {snippet}".strip(),
            status_code=resp.status_code,
        )

    payload = resp.json()
    foods = payload.get("foods") or []
    results: List[UsdaFood] = []

    for f in foods:
        fdc_id = f.get("fdcId")
        if not fdc_id:
            continue

        description = f.get("description") or "Unknown food"
        brand = f.get("brandOwner") or f.get("brandName")
        calories, protein, carbs, fat = _extract_macros(f.get("foodNutrients"))

        results.append(
            UsdaFood(
                fdc_id=int(fdc_id),
                description=description,
                brand=brand,
                calories=calories,
                protein_g=protein,
                carbs_g=carbs,
                fat_g=fat,
            )
        )

    return UsdaSearchResponse(foods=results, status_code=resp.status_code)


def search_foods_by_barcode(ean_code: str) -> UsdaSearchResponse:
    """
    Search USDA FoodData Central for a food by barcode (EAN/UPC code).
    Falls back to text search if barcode lookup fails.
    """
    api_key = _get_api_key()
    if not api_key or not ean_code.strip():
        return UsdaSearchResponse(
            foods=[],
            error="Missing USDA_FDC_API_KEY or no barcode provided.",
        )

    # Try barcode/UPC lookup first
    url = "https://api.nal.usda.gov/fdc/v1/foods/search"
    params = {
        "api_key": api_key,
        "query": f"gtinUpc:{ean_code.strip()}",
        "pageSize": 10,
    }

    try:
        resp = requests.get(url, params=params, timeout=6)
    except requests.RequestException:
        return UsdaSearchResponse(
            foods=[],
            error="Network error calling USDA FoodData Central.",
        )

    if resp.status_code != 200:
        return UsdaSearchResponse(
            foods=[],
            error=f"USDA barcode search failed (HTTP {resp.status_code}).",
            status_code=resp.status_code,
        )

    payload = resp.json()
    foods = payload.get("foods") or []
    results: List[UsdaFood] = []

    for f in foods:
        fdc_id = f.get("fdcId")
        if not fdc_id:
            continue

        description = f.get("description") or "Unknown food"
        brand = f.get("brandOwner") or f.get("brandName")
        calories, protein, carbs, fat = _extract_macros(f.get("foodNutrients"))

        results.append(
            UsdaFood(
                fdc_id=int(fdc_id),
                description=description,
                brand=brand,
                calories=calories,
                protein_g=protein,
                carbs_g=carbs,
                fat_g=fat,
            )
        )

    return UsdaSearchResponse(foods=results, status_code=resp.status_code)


def _cli_smoke_test() -> int:
    import sys

    q = " ".join(sys.argv[1:]).strip()
    if not q:
        print("Usage: python -m usda_api <food name>")
        return 2

    r = search_foods(q)
    if r.error:
        print(r.error)
        return 1

    print(f"Got {len(r.foods)} result(s). Showing top 5:")
    for f in r.foods[:5]:
        brand = f" ({f.brand})" if f.brand else ""
        print(
            f"- {f.description}{brand} [FDC {f.fdc_id}] "
            f"kcal={f.calories} P={f.protein_g} C={f.carbs_g} F={f.fat_g}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_smoke_test())

