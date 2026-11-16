from dataclasses import dataclass


@dataclass(slots=True)
class ServiceError(Exception):
    detail: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.detail
