"""Scalanie dwóch zapisów tej samej przestrzeni, żeby równoległe prośby nie kasowały sobie pól."""
from __future__ import annotations

import copy

_CASE_DICTS = (
    "positionReview", "criteria", "preliminary", "preparatoryService", "report",
    "review", "conclusion", "steps", "deadlines", "access",
)
_CASE_LISTS = {"observations": "id", "ratings": "criterionId", "documents": "id", "history": "id"}


def merge_state(fresh: dict, before: dict, after: dict) -> dict:
    """Nałóż na `fresh` tylko te pola, które w tej prośbie zmieniły się względem `before`."""
    out = copy.deepcopy(fresh)
    out["cases"] = _merge_records(
        fresh.get("cases") or [], before.get("cases") or [], after.get("cases") or [], "id", _merge_case)
    out["employees"] = _merge_records(
        fresh.get("employees") or [], before.get("employees") or [], after.get("employees") or [], "id", _take_after)
    out["notifications"] = _merge_records(
        fresh.get("notifications") or [], before.get("notifications") or [], after.get("notifications") or [], "id", _take_after)
    for key, value in after.items():
        if key in ("cases", "employees", "notifications"):
            continue
        if before.get(key) != value:
            out[key] = copy.deepcopy(value)
    return out


def _merge_case(fresh: dict, before: dict, after: dict) -> dict:
    out = copy.deepcopy(fresh)
    for key, value in after.items():
        if before.get(key) == value:
            continue
        if key in _CASE_DICTS and isinstance(value, dict):
            out[key] = _merge_dict(fresh.get(key) or {}, before.get(key) or {}, value)
        elif key in _CASE_LISTS and isinstance(value, list):
            out[key] = _merge_records(
                fresh.get(key) or [], before.get(key) or [], value, _CASE_LISTS[key], _take_after)
        else:
            out[key] = copy.deepcopy(value)
    for key in before:
        if key not in after:
            out.pop(key, None)
    return out


def _merge_dict(fresh: dict, before: dict, after: dict) -> dict:
    out = copy.deepcopy(fresh) if isinstance(fresh, dict) else {}
    for key, value in after.items():
        if before.get(key) == value:
            continue
        if isinstance(value, dict) and isinstance(before.get(key), dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], before[key], value)
        else:
            out[key] = copy.deepcopy(value)
    for key in before:
        if key not in after:
            out.pop(key, None)
    return out


def _take_after(_fresh: dict, _before: dict, after: dict) -> dict:
    return copy.deepcopy(after)


def _merge_records(fresh: list, before: list, after: list, id_key: str, merge_item) -> list:
    fresh_by = {item[id_key]: item for item in fresh if isinstance(item, dict) and item.get(id_key)}
    before_by = {item[id_key]: item for item in before if isinstance(item, dict) and item.get(id_key)}
    out: list = []
    seen: set = set()
    for item in after:
        if not isinstance(item, dict) or not item.get(id_key):
            continue
        item_id = item[id_key]
        seen.add(item_id)
        prev = before_by.get(item_id)
        if prev is None:
            out.append(copy.deepcopy(item))
        elif prev == item:
            if item_id in fresh_by:
                out.append(copy.deepcopy(fresh_by[item_id]))
        else:
            out.append(merge_item(fresh_by.get(item_id, prev), prev, item))
    for item in fresh:
        if not isinstance(item, dict) or not item.get(id_key) or item[id_key] in seen:
            continue
        # Było u nas i zniknęło z wyniku — usunęliśmy to w tej prośbie.
        if item[id_key] in before_by:
            continue
        out.append(copy.deepcopy(item))
    return out
