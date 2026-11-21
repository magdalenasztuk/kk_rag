"""Router aplikacji: te same ścieżki i semantyka co demonstracyjny backend frontu (`/api/...`)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from app.kompas.workspace import Workspace


@dataclass
class RouteContext:
    params: dict[str, str]
    query: dict[str, str]
    body: Any
    ws: Workspace
    user: dict

    def json(self) -> dict:
        return self.body if isinstance(self.body, dict) else {}


Handler = Callable[[RouteContext], Any]


@dataclass
class Route:
    method: str
    pattern: re.Pattern
    keys: list[str]
    handler: Handler
    ai: bool


class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, method: str, path: str, handler: Handler, ai: bool = False) -> "Router":
        keys: list[str] = []

        def key(m: re.Match) -> str:
            keys.append(m.group(1))
            return "([^/]+)"

        source = re.sub(r":([a-zA-Z]+)", key, path)
        self.routes.append(Route(method, re.compile(f"^{source}/?$"), keys, handler, ai))
        return self

    def get(self, path: str, handler: Handler, ai: bool = False) -> "Router":
        return self.add("GET", path, handler, ai)

    def post(self, path: str, handler: Handler, ai: bool = False) -> "Router":
        return self.add("POST", path, handler, ai)

    def put(self, path: str, handler: Handler, ai: bool = False) -> "Router":
        return self.add("PUT", path, handler, ai)

    def patch(self, path: str, handler: Handler, ai: bool = False) -> "Router":
        return self.add("PATCH", path, handler, ai)

    def delete(self, path: str, handler: Handler, ai: bool = False) -> "Router":
        return self.add("DELETE", path, handler, ai)

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str]] | None:
        from urllib.parse import unquote
        for route in self.routes:
            if route.method != method:
                continue
            m = route.pattern.match(path)
            if m:
                return route, {k: unquote(v) for k, v in zip(route.keys, m.groups())}
        return None
