"""
Inventory Capability routes.

Items:
  POST   /inventory/items         create item
  GET    /inventory/items/{id}    get item
  PATCH  /inventory/items/{id}    update item
  DELETE /inventory/items/{id}    delete item
  GET    /inventory/items         list items

Collections:
  POST   /inventory/collections           create collection
  GET    /inventory/collections/{id}      get collection
  PATCH  /inventory/collections/{id}      update collection
  DELETE /inventory/collections/{id}      delete collection
  GET    /inventory/collections           list collections
"""

from __future__ import annotations
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from contentbank.db.database import get_db
from contentbank.core import storage as store
from contentbank.core.models import Page
from contentbank.auth.dependencies import require_agent
from contentbank.capabilities.inventory.models import (
    InventoryItemCreate, InventoryItemUpdate, InventoryItemResponse,
    InventoryCollectionCreate, InventoryCollectionUpdate,
    InventoryCollectionResponse,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])

ITEM_SLUG = "inventory_item"
COLLECTION_SLUG = "inventory_collection"


def _to_item_data(body: InventoryItemCreate | InventoryItemUpdate) -> dict:
    d = {}
    scalar_fields = [
        "name", "description", "category", "condition",
        "quantity", "unit", "acquired_from", "value", "currency",
        "serial_number", "barcode", "related_object_ids",
    ]
    for f in scalar_fields:
        val = getattr(body, f, None)
        if val is not None:
            d[f] = val

    acquired_at = getattr(body, "acquired_at", None)
    if acquired_at is not None:
        d["acquired_at"] = acquired_at.isoformat() \
            if isinstance(acquired_at, datetime) else acquired_at

    location = getattr(body, "location", None)
    if location is not None:
        d["location"] = location.model_dump(exclude_none=True)

    return d


def _to_collection_data(
    body: InventoryCollectionCreate | InventoryCollectionUpdate,
) -> dict:
    d = {}
    for f in ("name", "description", "item_ids"):
        val = getattr(body, f, None)
        if val is not None:
            d[f] = val
    return d


# ---------------------------------------------------------------------------
# Item routes
# ---------------------------------------------------------------------------

@router.post("/items", response_model=InventoryItemResponse, status_code=201)
async def create_item(
    body: InventoryItemCreate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        obj = await store.objects.create_object(
            db,
            type_slug=ITEM_SLUG,
            owner_id=body.owner,
            scope=body.scope,
            capability_data=_to_item_data(body),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return InventoryItemResponse.from_object_row(obj)


@router.get("/items/{item_id}", response_model=InventoryItemResponse)
async def get_item(
    item_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        obj = await store.objects.get_object(
            db, obj_id=item_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Item not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")
    if obj.type_slug != ITEM_SLUG:
        raise HTTPException(status_code=404, detail="Item not found")
    return InventoryItemResponse.from_object_row(obj)


@router.patch("/items/{item_id}", response_model=InventoryItemResponse)
async def update_item(
    item_id: str,
    body: InventoryItemUpdate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        obj = await store.objects.update_object(
            db, obj_id=item_id,
            requesting_agent_id=requesting_agent_id,
            metadata=_to_item_data(body),
            scope=body.scope,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Item not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return InventoryItemResponse.from_object_row(obj)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        await store.objects.delete_object(
            db, obj_id=item_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Item not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/items", response_model=Page)
async def list_items(
    owner: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("-updated_at"),
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    objects, next_cursor = await store.objects.list_objects(
        db,
        requesting_agent_id=requesting_agent_id,
        type_slug=ITEM_SLUG,
        owner=owner,
        scope=scope,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )
    return Page(
        items=[InventoryItemResponse.from_object_row(o) for o in objects],
        cursor=next_cursor,
        has_more=next_cursor is not None,
    )


# ---------------------------------------------------------------------------
# Collection routes
# ---------------------------------------------------------------------------

@router.post("/collections",
             response_model=InventoryCollectionResponse, status_code=201)
async def create_collection(
    body: InventoryCollectionCreate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        obj = await store.objects.create_object(
            db,
            type_slug=COLLECTION_SLUG,
            owner_id=body.owner,
            scope=body.scope,
            capability_data=_to_collection_data(body),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return InventoryCollectionResponse.from_object_row(obj)


@router.get("/collections/{coll_id}",
            response_model=InventoryCollectionResponse)
async def get_collection(
    coll_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        obj = await store.objects.get_object(
            db, obj_id=coll_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")
    if obj.type_slug != COLLECTION_SLUG:
        raise HTTPException(status_code=404, detail="Collection not found")
    return InventoryCollectionResponse.from_object_row(obj)


@router.patch("/collections/{coll_id}",
              response_model=InventoryCollectionResponse)
async def update_collection(
    coll_id: str,
    body: InventoryCollectionUpdate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        obj = await store.objects.update_object(
            db, obj_id=coll_id,
            requesting_agent_id=requesting_agent_id,
            metadata=_to_collection_data(body),
            scope=body.scope,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return InventoryCollectionResponse.from_object_row(obj)


@router.delete("/collections/{coll_id}", status_code=204)
async def delete_collection(
    coll_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        await store.objects.delete_object(
            db, obj_id=coll_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Collection not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/collections", response_model=Page)
async def list_collections(
    owner: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("-updated_at"),
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    objects, next_cursor = await store.objects.list_objects(
        db,
        requesting_agent_id=requesting_agent_id,
        type_slug=COLLECTION_SLUG,
        owner=owner,
        scope=scope,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )
    return Page(
        items=[InventoryCollectionResponse.from_object_row(o) for o in objects],
        cursor=next_cursor,
        has_more=next_cursor is not None,
    )
