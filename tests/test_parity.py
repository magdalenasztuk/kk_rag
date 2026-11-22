"""Zgodność backendu Python z backendem demonstracyjnym frontu (ten sam scenariusz żądań, te same odpowiedzi).

Wzorzec `tests/parity/expected.json` generuje front: `npm run parity:trace -- <flow.json> <expected.json>`.
Porównanie pomija wartości zmienne: identyfikatory nadawane w trakcie i bieżącą godzinę.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("KOMPAS_DENSE_ENABLED", "false")
os.environ.setdefault("KOMPAS_USE_RERANKER", "false")

from app.core.config import settings  # noqa: E402
from app.kompas import api  # noqa: E402
from app.kompas.errors import ApiError  # noqa: E402

PARITY = Path(__file__).parent / "parity"
GENERATED_ID = re.compile(r"^(obs|case|doc|h|n|ans|goal)-[0-9a-z]{10}$")
NOW = re.compile(r"^2026-11-21T\d{2}:\d{2}:\d{2}\.000Z$")
AUTH_TOKEN = re.compile(r"^(mock\.[A-Za-z0-9_-]+|[A-Za-z0-9_\-=]+)$")


class MemoryStore:
    kind = "memory"

    def __init__(self):
        self.data: dict[str, str] = {}

    def load(self, workspace_id):
        return self.data.get(workspace_id)

    def save(self, workspace_id, state_json):
        self.data[workspace_id] = state_json


def normalize(value):
    if isinstance(value, dict):
        # Etykieta silnika analizy różni się celowo (mock frontu vs. backend).
        out = {}
        for k, v in value.items():
            if k == "model" and isinstance(v, str):
                out[k] = "<model>"
            elif k == "token" and isinstance(v, str):
                out[k] = "<token>"
            elif k == "expiresAt" and isinstance(v, str):
                out[k] = "<expires>"
            else:
                out[k] = normalize(v)
        return out
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, str):
        if GENERATED_ID.match(value):
            return f"<{value.split('-')[0]}-id>"
        if NOW.match(value):
            return "<now>"
        if value.startswith("mock.") or (len(value) > 40 and AUTH_TOKEN.match(value)):
            return "<token>"
        value = re.sub(r"\b(obs|case|doc|h|n)-[0-9a-z]{10}\b", lambda m: f"<{m.group(1)}-id>", value)
    return value


def pick(value, path: str):
    for key in path.split("."):
        if isinstance(value, list):
            value = value[int(key)] if value else None
        elif isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def diff(a, b, path="$"):
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return [f"{path}: {json.dumps(a, ensure_ascii=False)[:160]} != {json.dumps(b, ensure_ascii=False)[:160]}"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: {'missing in python' if k not in a else 'extra in python'}")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: len {len(a)} != {len(b)}"] + diff(a[:min(len(a), len(b))], b[:min(len(a), len(b))], path)
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f"{path}[{i}]")]
    if isinstance(a, float) or isinstance(b, float):
        return [] if abs(a - b) < 1e-9 else [f"{path}: {a} != {b}"]
    return [] if a == b else [f"{path}: {json.dumps(a, ensure_ascii=False)[:200]} != {json.dumps(b, ensure_ascii=False)[:200]}"]


def run_flow(steps):
    store = MemoryStore()
    variables: dict[str, object] = {}
    fill = lambda text: re.sub(r"\$\{(\w+)\}", lambda m: str(variables.get(m.group(1), "")), text)  # noqa: E731
    api.get_store = lambda: store  # type: ignore[assignment]
    token = api.handle("POST", "/auth/login", {}, {"login": "piotr", "password": "piotr"}, "parity-test")["token"]
    results = []
    for step in steps:
        path = fill(step["p"])
        route, _, qs = path.partition("?")
        query = dict(p.split("=", 1) for p in qs.split("&") if p) if qs else {}
        body = json.loads(fill(json.dumps(step["b"], ensure_ascii=False))) if "b" in step else None
        try:
            result = json.loads(json.dumps(api.handle(
                step["m"], route, query, body, "parity-test", f"Bearer {token}")))
            if step["p"] == "/auth/login" and isinstance(result, dict) and result.get("token"):
                token = result["token"]
            for name, p in (step.get("save") or {}).items():
                variables[name] = pick(result, p)
            results.append({"status": 200, "body": result})
        except ApiError as e:
            results.append({"status": e.status, "body": e.body})
    return results


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_flow_matches_frontend_mock():
    steps = json.loads((PARITY / "flow.json").read_text(encoding="utf-8"))
    expected = json.loads((PARITY / "expected.json").read_text(encoding="utf-8"))
    actual = run_flow(steps)
    problems = []
    for i, (step, exp, act) in enumerate(zip(steps, expected, actual)):
        keys = step.get("cmp")
        e, a = normalize(exp), normalize(act)
        if keys and e["status"] == 200 and a["status"] == 200:
            e = {"status": 200, "body": {k: e["body"].get(k) for k in keys}}
            a = {"status": 200, "body": {k: a["body"].get(k) for k in keys}}
        found = diff(a, e)
        if found:
            problems.append(f"#{i} {step['m']} {step['p']}:\n    " + "\n    ".join(found[:12]))
    assert not problems, f"{len(problems)} niezgodnych odpowiedzi:\n" + "\n".join(problems[:25])
