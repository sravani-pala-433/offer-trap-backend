from dataclasses import dataclass
from enum import Enum
from typing import NoReturn
from fastapi import status


@dataclass
class AppError:
    name: str
    error_type: str
    details: str
    status_code: int


class ServiceError(Enum):

    UNAUTHORIZED = AppError(
        name="UNAUTHORIZED",
        error_type="AuthenticationError",
        details="Unauthorized access.",
        status_code=status.HTTP_401_UNAUTHORIZED
    )

    INVALID_TOKEN = AppError(
        name="INVALID_TOKEN",
        error_type="AuthenticationError",
        details="Invalid refresh token.",
        status_code=status.HTTP_401_UNAUTHORIZED
    )

    FORBIDDEN = AppError(
        name="FORBIDDEN",
        error_type="AuthorizationError",
        details="Access forbidden.",
        status_code=status.HTTP_403_FORBIDDEN
    )




def raise_app_exception(app_error: ServiceError, additional_details: str = None) -> NoReturn:
    details = app_error.value.details
    if additional_details:
        details = f"{details} {additional_details}"
    raise AppException(
        error_code=app_error.value.name,
        error_type=app_error.value.error_type,
        details=details,
        status_code=app_error.value.status_code
    )

