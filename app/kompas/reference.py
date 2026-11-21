"""Dane referencyjne: struktura urzędu, OSP, model kompetencji, baza wiedzy aplikacji.

Pliki w `seed/` eksportuje skrypt frontu `npm run export:seed` — jedno źródło danych demo dla obu warstw.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.kompas.errors import not_found

SEED_DIR = Path(__file__).resolve().parent / "seed"


def _load(name: str):
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def reference() -> dict:
    return _load("reference.json")


@lru_cache(maxsize=1)
def competency_model() -> dict:
    return _load("model.json")


@lru_cache(maxsize=1)
def app_knowledge() -> dict:
    return _load("knowledge.json")


@lru_cache(maxsize=1)
def intents() -> dict:
    return _load("intents.json")


@lru_cache(maxsize=4)
def scenario_state(scenario_id: str) -> str:
    return (SEED_DIR / f"state-{scenario_id}.json").read_text(encoding="utf-8")


def users() -> list[dict]:
    return reference()["users"]


def employees() -> list[dict]:
    return reference()["employees"]


def scenarios() -> list[dict]:
    return reference()["scenarios"]


def recruitments() -> list[dict]:
    return reference()["recruitments"]


def _find(items: list[dict], id_: str, what: str) -> dict:
    found = next((item for item in items if item["id"] == id_), None)
    if not found:
        raise not_found(what)
    return found


def user(id_: str) -> dict:
    return _find(users(), id_, "użytkownik")


def employee(id_: str) -> dict:
    return _find(employees(), id_, "pracownik")


def position(id_: str) -> dict:
    return _find(reference()["positions"], id_, "stanowisko")


def org_unit(id_: str) -> dict:
    return _find(reference()["orgUnits"], id_, "komórka organizacyjna")


def positions_in_unit(org_unit_id: str) -> list[dict]:
    return [p for p in reference()["positions"] if p["orgUnitId"] == org_unit_id]


def competency(criterion_id: str) -> dict | None:
    return next((c for c in competency_model()["competencies"] if c["id"] == criterion_id), None)


def indicator_count(criterion_id: str) -> int:
    c = competency(criterion_id)
    return len(c["indicators"]) if c else 0


def person_ref(u: dict) -> dict:
    return {"id": u["id"], "fullName": u["fullName"], "jobTitle": u["jobTitle"]}
