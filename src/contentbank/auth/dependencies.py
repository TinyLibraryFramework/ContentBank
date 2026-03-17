"""
FastAPI auth dependencies.

Usage in routes:
    from contentbank.auth.dependencies import require_agent

    @router.get("/objects/{id}")
    async def get_object(
        object_id: str,
        agent_id: str = Depends(require_agent),
        db: AsyncSession = Depends(get_db),
    ):
        ...
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from contentbank.auth.tokens import verify_agent_token, verify_node_token, TokenError

_bearer = HTTPBearer(auto_error=False)


async def require_agent(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Verify a Bearer JWT and return the agent_id.
    Raises HTTP 401 if missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        agent_id = verify_agent_token(credentials.credentials)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return agent_id


async def require_node(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Verify a node_sync Bearer JWT and return the node_id.
    Used on replication endpoints.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Node authorization required",
        )

    try:
        node_id = verify_node_token(credentials.credentials)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    return node_id
