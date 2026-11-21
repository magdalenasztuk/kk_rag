"""REGUŁA NARZĘDZIA (nie przepis): sugestia oceny cząstkowej z wybranych opisów zachowań.

Model kompetencji nie określa agregacji wskaźników, więc reguła jest jawna i wersjonowana,
a jej wynik to wyłącznie sugestia — decyduje przełożony.
"""
from __future__ import annotations

from app.domain.scales import overall_level_for

RULES_VERSION = "kompas-2026.1"
PERIODIC_LEVEL_POINTS = {1: 1, 2: 3, 3: 5, 4: 7, 5: 9}
FIRST_LEVEL_POINTS = {1: 3, 2: 3, 3: 5, 4: 7, 5: 7}

_LEVEL_TO_PERIODIC_POINTS = {"znacznie-ponizej": 1, "ponizej": 3, "na-poziomie": 5, "powyzej": 7, "znacznie-powyzej": 9}


def level_to_points(path: str, level: int) -> int:
    return (FIRST_LEVEL_POINTS if path == "first" else PERIODIC_LEVEL_POINTS)[level]


def average_to_points(path: str, total: float, count: int) -> int:
    if path == "first":
        if total <= 4 * count:
            return 3
        if total <= 6 * count:
            return 5
        return 7
    return _LEVEL_TO_PERIODIC_POINTS.get(overall_level_for(total, count)["id"], 5)


def suggest_criterion_score(path: str, indicators: list[dict], total_indicators: int | None = None) -> dict:
    total_indicators = len(indicators) if total_indicators is None else total_indicators
    contributions, no_basis = [], 0
    for item in indicators:
        if item.get("noBasis"):
            no_basis += 1
        elif item.get("level") is not None:
            contributions.append({
                "indicatorId": item["indicatorId"],
                "level": item["level"],
                "points": level_to_points(path, item["level"]),
            })
    assessed = len(contributions)
    pending = max(total_indicators - assessed - no_basis, 0)
    if assessed == 0:
        return {"total": total_indicators, "assessedCount": 0, "noBasisCount": no_basis, "pendingCount": pending,
                "contributions": [], "average": None, "points": None, "insufficientEvidence": True}
    total = sum(c["points"] for c in contributions)
    return {"total": total_indicators, "assessedCount": assessed, "noBasisCount": no_basis, "pendingCount": pending,
            "contributions": contributions, "average": total / assessed,
            "points": average_to_points(path, total, assessed), "insufficientEvidence": False}
