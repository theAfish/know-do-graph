from __future__ import annotations


class ServiceError(Exception):
    """Base class for service-layer failures."""

    code = "service_error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict:
        return {"error": self.code, "message": str(self)}


class NotFoundError(ServiceError):
    code = "not_found"
    status_code = 404


class ValidationServiceError(ServiceError):
    code = "validation_error"
    status_code = 400
