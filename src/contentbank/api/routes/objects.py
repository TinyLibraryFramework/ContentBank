"""
Generic object CRUD routes.
Capability-specific routes (calendar, inventory) extend these patterns.
"""

from __future__ import annotations
import base64, json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from contentbank.db.database import get_db
from contentbank.db.models import Object as ObjectRow
from contentbank.core.models import ObjectResponse, BlobAttachmentModel, Page
from contentbank.core import storage as store
from contentbank.auth.dependencies import require_agent

router = APIRouter(prefix="/objects", tags=["objects"])


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class BlobInput(BaseModel):
    cid: str
    mime_type: str
    blob_role: str
    byte_size: Optional[int] = None
    content_hash: Optional[str] = None


class ObjectCreateRequest(BaseModel):
    type_slug: str
    owner: str
    scope: str
    metadata: dict = {}
    blobs: list[BlobInput] = []


class ObjectUpdateRequest(BaseModel):
    metadata: Optional[dict] = None
    scope: Optional[str] = None
    blobs_add: list[BlobInput] = []
    blobs_remove: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_response(obj: ObjectRow) -> ObjectResponse:
    return ObjectResponse(
        id=obj.id,
        type_slug=obj.type_slug,
        owner=obj.owner_agent_id or obj.owner_group_id,
        scope=obj.scope,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        source_node=obj.source_node,
        content_hash=obj.content_hash,
        blobs=[
            BlobAttachmentModel(
                cid=b.cid,
                mime_type=b.mime_type,
                blob_role=b.blob_role,
                byte_size=b.byte_size,
                content_hash=b.content_hash,
            )
            for b in (obj.blobs or [])
        ],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=ObjectResponse, status_code=201)
async def create_object(
    body: ObjectCreateRequest,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new ContentBank object.
    Runs SHACL validation before write.
    """
    try:
        obj = await store.objects.create_object(
            db,
            type_slug=body.type_slug,
            owner_id=body.owner,
            scope=body.scope,
            capability_data=body.metadata,
            blobs=[b.model_dump() for b in body.blobs],
            source_node=None,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return _row_to_response(obj)


@router.get("/{object_id}", response_model=ObjectResponse)
async def get_object(
    object_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a ContentBank object by ID. Access enforced by scope rules."""
    try:
        obj = await store.objects.get_object(
            db,
            obj_id=object_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Object not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")

    return _row_to_response(obj)


@router.patch("/{object_id}", response_model=ObjectResponse)
async def update_object(
    object_id: str,
    body: ObjectUpdateRequest,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Update mutable fields of an object. Requester must be the owner."""
    try:
        obj = await store.objects.update_object(
            db,
            obj_id=object_id,
            requesting_agent_id=requesting_agent_id,
            metadata=body.metadata,
            scope=body.scope,
            blobs_add=[b.model_dump() for b in body.blobs_add],
            blobs_remove=body.blobs_remove,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Object not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return _row_to_response(obj)


@router.delete("/{object_id}", status_code=204)
async def delete_object(
    object_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Delete a ContentBank object. Requester must be the owner."""
    try:
        await store.objects.delete_object(
            db,
            obj_id=object_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Object not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/", response_model=Page)
async def list_objects(
    type_slug: Optional[str] = Query(None),
    owner: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("-updated_at"),
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """List ContentBank objects visible to the requesting agent."""
    objects, next_cursor = await store.objects.list_objects(
        db,
        requesting_agent_id=requesting_agent_id,
        type_slug=type_slug,
        owner=owner,
        scope=scope,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )

    return Page(
        items=[_row_to_response(obj) for obj in objects],
        cursor=next_cursor,
        has_more=next_cursor is not None,
    )
