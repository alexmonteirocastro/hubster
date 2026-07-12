from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db.settings import Settings, get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


def require_api_key(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Missing or invalid Authorization header.",
                "code": "missing_api_key",
            },
        )
    if credentials.credentials not in settings.hubster_api_keys:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "API key is not authorized.",
                "code": "invalid_api_key",
            },
        )
