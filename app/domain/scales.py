"""Skale ocen: okresowa 1/3/5/7/9 (§ 11 rozporządzenia z 2016 r.), pierwsza 3/5/7 (§ 9 rozporządzenia z 2015 r.)."""
from __future__ import annotations

PERIODIC_SCALE = [
    {"points": 1, "label": "Znacznie poniżej oczekiwań"},
    {"points": 3, "label": "Poniżej oczekiwań"},
    {"points": 5, "label": "Na poziomie oczekiwań"},
    {"points": 7, "label": "Powyżej oczekiwań"},
    {"points": 9, "label": "Znacznie powyżej oczekiwań"},
]

FIRST_SCALE = [
    {"points": 3, "label": "Poniżej oczekiwań"},
    {"points": 5, "label": "Na poziomie oczekiwań"},
    {"points": 7, "label": "Powyżej oczekiwań"},
]

OVERALL_LEVELS = {
    "znacznie-ponizej": {"id": "znacznie-ponizej", "label": "Znacznie poniżej oczekiwań", "range": "1–2", "positiveEligible": False},
    "ponizej": {"id": "ponizej", "label": "Poniżej oczekiwań", "range": "powyżej 2–4", "positiveEligible": False},
    "na-poziomie": {"id": "na-poziomie", "label": "Na poziomie oczekiwań", "range": "powyżej 4–6", "positiveEligible": True},
    "powyzej": {"id": "powyzej", "label": "Powyżej oczekiwań", "range": "powyżej 6–8", "positiveEligible": True},
    "znacznie-powyzej": {"id": "znacznie-powyzej", "label": "Znacznie powyżej oczekiwań", "range": "powyżej 8–9", "positiveEligible": True},
}


def scale_for(path: str) -> list[dict]:
    return FIRST_SCALE if path == "first" else PERIODIC_SCALE


def points_label(points: int | None) -> str:
    return next((o["label"] for o in PERIODIC_SCALE if o["points"] == points), "—")


def is_valid_points(path: str, points: object) -> bool:
    return isinstance(points, (int, float)) and any(o["points"] == points for o in scale_for(path))


def overall_level_for(total: float, count: int) -> dict:
    """Porównujemy sumy zamiast średnich — granice (np. dokładnie 6,00) nie zależą od zaokrągleń."""
    if count <= 0:
        raise ValueError("Brak ocen do wyznaczenia poziomu.")
    if total <= 2 * count:
        return OVERALL_LEVELS["znacznie-ponizej"]
    if total <= 4 * count:
        return OVERALL_LEVELS["ponizej"]
    if total <= 6 * count:
        return OVERALL_LEVELS["na-poziomie"]
    if total <= 8 * count:
        return OVERALL_LEVELS["powyzej"]
    return OVERALL_LEVELS["znacznie-powyzej"]
