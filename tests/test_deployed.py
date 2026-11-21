"""Ten sam scenariusz co `test_parity`, ale przez HTTP na działającym wdrożeniu (np. Vercel).

    KOMPAS_E2E_URL=https://<backend>.vercel.app .venv/bin/python -m pytest tests/test_deployed.py -q
"""
from __future__ import annotations

import json
import os
import re
import uuid

import httpx
import pytest

from tests.test_parity import PARITY, diff, normalize, pick

URL = os.environ.get("KOMPAS_E2E_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(not URL, reason="ustaw KOMPAS_E2E_URL, aby sprawdzić wdrożenie")


def test_deployed_flow_matches_frontend_mock():
    steps = json.loads((PARITY / "flow.json").read_text(encoding="utf-8"))
    expected = json.loads((PARITY / "expected.json").read_text(encoding="utf-8"))
    variables: dict[str, object] = {}
    fill = lambda text: re.sub(r"\$\{(\w+)\}", lambda m: str(variables.get(m.group(1), "")), text)  # noqa: E731
    headers = {"X-Kompas-Workspace": f"e2e-{uuid.uuid4().hex[:12]}"}
    problems = []
    with httpx.Client(base_url=f"{URL}/api", headers=headers, timeout=90) as client:
        for i, (step, exp) in enumerate(zip(steps, expected)):
            body = json.loads(fill(json.dumps(step["b"], ensure_ascii=False))) if "b" in step else None
            r = client.request(step["m"], fill(step["p"]), json=body)
            act = {"status": r.status_code, "body": r.json()}
            if r.status_code == 200:
                for name, p in (step.get("save") or {}).items():
                    variables[name] = pick(act["body"], p)
            keys = step.get("cmp")
            e, a = normalize(exp), normalize(act)
            if keys and e["status"] == 200 and a["status"] == 200:
                e = {"status": 200, "body": {k: e["body"].get(k) for k in keys}}
                a = {"status": 200, "body": {k: a["body"].get(k) for k in keys}}
            found = diff(a, e)
            if found:
                problems.append(f"#{i} {step['m']} {step['p']}:\n    " + "\n    ".join(found[:6]))
    assert not problems, f"{len(problems)} niezgodnych odpowiedzi:\n" + "\n".join(problems[:25])
