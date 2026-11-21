"""Katalog kryteriów oceny (zał. nr 1 do rozporządzenia PRM z 4.04.2016 r., Dz.U. poz. 470).

Identyfikatory odpowiadają kompetencjom w modelu organizatora (c01–c14) — mapowanie 1:1.
"""
from __future__ import annotations

CRITERIA: dict[str, dict] = {
    "c01": {"name": "Rzetelność", "shortName": "Rzetelność", "annexNo": 8},
    "c02": {"name": "Komunikacja", "shortName": "Komunikacja", "annexNo": 1},
    "c03": {"name": "Wykorzystywanie wiedzy i doskonalenie zawodowe", "shortName": "Wykorzystywanie wiedzy", "annexNo": 10},
    "c04": {"name": "Organizacja pracy i orientacja na osiąganie celów", "shortName": "Organizacja pracy", "annexNo": 4},
    "c05": {"name": "Kreatywność", "shortName": "Kreatywność", "annexNo": 2},
    "c06": {"name": "Współpraca", "shortName": "Współpraca", "annexNo": 11},
    "c07": {"name": "Myślenie analityczne", "shortName": "Myślenie analityczne", "annexNo": 9},
    "c08": {"name": "Negocjowanie", "shortName": "Negocjowanie", "annexNo": 3},
    "c09": {"name": "Wystąpienia publiczne", "shortName": "Wystąpienia publiczne", "annexNo": 12},
    "c10": {"name": "Orientacja na klienta/interesanta", "shortName": "Orientacja na klienta", "annexNo": 5},
    "c11": {"name": "Radzenie sobie w sytuacjach kryzysowych", "shortName": "Sytuacje kryzysowe", "annexNo": 7},
    "c12": {"name": "Zarządzanie strategiczne", "shortName": "Zarządzanie strategiczne", "annexNo": 14},
    "c13": {"name": "Zarządzanie ludźmi", "shortName": "Zarządzanie ludźmi", "annexNo": 13},
    "c14": {"name": "Podejmowanie decyzji i odpowiedzialność", "shortName": "Podejmowanie decyzji", "annexNo": 6},
}

ALL_CRITERION_IDS = list(CRITERIA)

# § 4 ust. 2–3 rozporządzenia z 2016 r. — kolejność z arkusza.
MANDATORY_CRITERIA = {
    "B": ["c13", "c14", "c04", "c06", "c02"],
    "C": ["c03", "c01", "c04", "c06", "c02"],
}

# § 2 rozporządzenia PRM z 23.07.2015 r. (Dz.U. poz. 1144).
FIRST_ASSESSMENT_ELEMENTS = ["c01", "c03", "c04", "c02", "c06"]

MAX_ADDITIONAL_CRITERIA = 3


def is_criterion_id(value: str) -> bool:
    return value in CRITERIA


def criterion_name(cid: str) -> str:
    return CRITERIA[cid]["name"] if cid in CRITERIA else cid


def mandatory_criteria_for(path: str, variant: str | None) -> list[str]:
    if path == "first":
        return FIRST_ASSESSMENT_ELEMENTS
    return MANDATORY_CRITERIA[variant] if variant in MANDATORY_CRITERIA else []


def additional_criteria_candidates(variant: str) -> list[str]:
    mandatory = set(MANDATORY_CRITERIA[variant])
    return sorted((c for c in ALL_CRITERION_IDS if c not in mandatory), key=lambda c: CRITERIA[c]["annexNo"])
