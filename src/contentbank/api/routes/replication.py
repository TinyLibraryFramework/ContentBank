"""
Replication sync endpoint.
Peer nodes pull changes since a given sequence number.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from contentbank.db.database import get_db
from contentbank.auth.dependencies import require_node
from contentbank.replication.sync import get_events_since

router = APIRouter(prefix="/replication", tags=["replication"])


class SyncEvent(BaseModel):
    node_id: str
    node_seq: int
    object_id: str
    change_type: str
    updated_at: str
    object_payload: Optional[dict] = None
    scope_group_dep_node: Optional[str] = None
    scope_group_dep_seq: Optional[int] = None


class SyncResponse(BaseModel):
    events: list[SyncEvent]
    has_more: bool
    node_id: str


@router.get("/sync", response_model=SyncResponse)
async def sync(
    since: int = Query(0, description="Return events with seq > since"),
    limit: int = Query(500, ge=1, le=500),
    requesting_node_id: str = Depends(require_node),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull replication events since a given sequence number.
    Authenticated with a node_sync JWT.
    """
    from contentbank.config import settings

    events, has_more = await get_events_since(db, since, limit)

    return SyncResponse(
        events=[SyncEvent(**e) for e in events],
        has_more=has_more,
        node_id=settings.node_id,
    )
