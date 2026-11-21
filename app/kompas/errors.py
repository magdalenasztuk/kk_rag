from __future__ import annotations


class ApiError(Exception):
    """Błąd domenowy zwracany jako `{code, message, issues?}` — ten sam kształt co w mocku frontu."""

    def __init__(self, status: int, code: str, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.body = {"code": code, "message": message, **({"issues": issues} if issues is not None else {})}


def not_found(what: str) -> ApiError:
    return ApiError(404, "not-found", f"Nie znaleziono: {what}.")


def forbidden(message: str = "Nie masz dostępu do tego zasobu.") -> ApiError:
    return ApiError(403, "forbidden", message)


def bad_request(message: str) -> ApiError:
    return ApiError(400, "bad-request", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def unprocessable(message: str, issues: list[str] | None = None) -> ApiError:
    return ApiError(422, "validation", message, issues or [])
