"""Stan jednej przestrzeni roboczej: sprawy, powiadomienia, przypomnienia, kandydaci."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from app.kompas import reference as ref
from app.kompas.errors import not_found
from app.kompas.store import WorkspaceStore

STATE_VERSION = 9
DEFAULT_USER_ID = "u-piotr"
DEFAULT_WORKSPACE = "default"
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_WARSAW = timezone(timedelta(hours=1))


def valid_workspace_id(value: str | None) -> str | None:
    return value if value and _WORKSPACE_ID.match(value) else None


def seeded_state(scenario_id: str = "demo", session_user_id: str = DEFAULT_USER_ID) -> dict:
    state = json.loads(ref.scenario_state(scenario_id))
    state["sessionUserId"] = session_user_id
    state.setdefault("employees", [])
    state["version"] = STATE_VERSION
    return state


class Workspace:
    def __init__(self, workspace_id: str, store: WorkspaceStore):
        self.id = workspace_id
        self._store = store
        self.dirty = False
        raw = store.load(workspace_id)
        state = json.loads(raw) if raw else None
        if not state or state.get("version") != STATE_VERSION:
            state = seeded_state()
            self.dirty = True
        self.state: dict = state

    # — persistence —

    def commit(self) -> None:
        if self.dirty:
            self._store.save(self.id, json.dumps(self.state, ensure_ascii=False))
            self.dirty = False

    def touch(self) -> None:
        self.dirty = True

    def reset(self, scenario_id: str = "demo", session_user_id: str | None = None) -> None:
        self.state = seeded_state(scenario_id, session_user_id or self.state.get("sessionUserId", DEFAULT_USER_ID))
        self.dirty = True

    # — time —

    @property
    def today(self) -> str:
        return self.state["today"]

    def now(self) -> str:
        """Data demonstracyjna + rzeczywista godzina (czas „ścienny”)."""
        return f"{self.today}T{datetime.now(_WARSAW).strftime('%H:%M:%S')}.000Z"

    # — people —

    def session_user(self) -> dict:
        return ref.user(self.state["sessionUserId"])

    def employees(self) -> list[dict]:
        extras = self.state.setdefault("employees", [])
        by_id = {e["id"]: e for e in ref.employees()}
        for employee in extras:
            by_id[employee["id"]] = employee
        return list(by_id.values())

    def employee(self, employee_id: str) -> dict:
        found = next((e for e in self.employees() if e["id"] == employee_id), None)
        if not found:
            raise not_found("pracownik")
        return found

    def save_employee(self, employee: dict) -> dict:
        extras = self.state.setdefault("employees", [])
        index = next((i for i, item in enumerate(extras) if item["id"] == employee["id"]), None)
        if index is None:
            extras.append(employee)
        else:
            extras[index] = employee
        self.dirty = True
        return employee

    # — cases —

    @property
    def cases(self) -> list[dict]:
        return self.state["cases"]

    def find_case(self, case_id: str) -> dict:
        found = next((c for c in self.cases if c["id"] == case_id), None)
        if not found:
            raise not_found("ocena")
        return found

    def save_case(self, case: dict) -> dict:
        case["updatedAt"] = self.now()
        index = next((i for i, c in enumerate(self.cases) if c["id"] == case["id"]), None)
        if index is None:
            self.cases.insert(0, case)
        else:
            self.cases[index] = case
        self.dirty = True
        return case

    def notify(self, notification: dict) -> None:
        from app.domain.text import new_id
        self.state["notifications"].insert(0, {**notification, "id": new_id("n"), "createdAt": self.now()})
        self.dirty = True
