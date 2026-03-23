"""Local loopback Open API services for GUI-integrated automation."""

from .contracts import (
    describe_local_open_api_route,
    iter_local_open_api_route_descriptions,
    LOCAL_OPEN_API_DEFAULT_PORT,
    LOCAL_OPEN_API_ROUTE_ALLOWLIST,
    LOCAL_OPEN_API_ROUTE_SPECS,
    LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS,
    LOCAL_OPEN_API_VALIDATION_MODES,
)
from .dispatch import MainThreadDispatcher
from .service import LocalOpenApiController, LocalOpenApiService

__all__ = [
    "LOCAL_OPEN_API_DEFAULT_PORT",
    "LOCAL_OPEN_API_ROUTE_ALLOWLIST",
    "LOCAL_OPEN_API_ROUTE_SPECS",
    "LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS",
    "LOCAL_OPEN_API_VALIDATION_MODES",
    "describe_local_open_api_route",
    "iter_local_open_api_route_descriptions",
    "LocalOpenApiController",
    "LocalOpenApiService",
    "MainThreadDispatcher",
]
