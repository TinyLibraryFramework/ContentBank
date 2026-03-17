"""
Pydantic models for the Inventory Capability.
Maps to shapes/capability/inventory/shapes.ttl — tlinv: namespace.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

class LocationModel(BaseModel):
    label: str                          # e.g. "Shed > Top shelf"
    geo_lat: Optional[float] = None
    geo_long: Optional[float] = None
    node_id: Optional[str] = None       # urn:cb:node:{uuid}


# ---------------------------------------------------------------------------
# InventoryItem — create / update
# ---------------------------------------------------------------------------

class InventoryItemCreate(BaseModel):
    """Input for POST /inventory/items"""
    owner: str
    scope: str

    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    condition: Optional[str] = None     # new|good|fair|poor|unknown
    quantity: Optional[float] = None
    unit: Optional[str] = None          # kg, each, litre, etc.
    location: Optional[LocationModel] = None
    acquired_at: Optional[datetime] = None
    acquired_from: Optional[str] = None
    value: Optional[float] = None
    currency: Optional[str] = None      # ISO 4217
    serial_number: Optional[str] = None
    barcode: Optional[str] = None
    related_object_ids: list[str] = []


class InventoryItemUpdate(BaseModel):
    """Input for PATCH /inventory/items/{id}"""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    location: Optional[LocationModel] = None
    acquired_at: Optional[datetime] = None
    acquired_from: Optional[str] = None
    value: Optional[float] = None
    currency: Optional[str] = None
    serial_number: Optional[str] = None
    barcode: Optional[str] = None
    related_object_ids: Optional[list[str]] = None
    scope: Optional[str] = None


# ---------------------------------------------------------------------------
# InventoryItem — response
# ---------------------------------------------------------------------------

class InventoryItemResponse(BaseModel):
    id: str
    type_slug: str = "inventory_item"
    owner: str
    scope: str
    created_at: datetime
    updated_at: datetime
    source_node: Optional[str] = None
    content_hash: Optional[str] = None

    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    location: Optional[LocationModel] = None
    acquired_at: Optional[datetime] = None
    acquired_from: Optional[str] = None
    value: Optional[float] = None
    currency: Optional[str] = None
    serial_number: Optional[str] = None
    barcode: Optional[str] = None
    related_object_ids: list[str] = []

    @classmethod
    def from_object_row(cls, obj) -> InventoryItemResponse:
        d = obj.capability_data or {}
        loc = LocationModel(**d["location"]) if d.get("location") else None
        return cls(
            id=obj.id,
            owner=obj.owner_agent_id or obj.owner_group_id,
            scope=obj.scope,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            source_node=obj.source_node,
            content_hash=obj.content_hash,
            name=d.get("name", ""),
            description=d.get("description"),
            category=d.get("category"),
            condition=d.get("condition"),
            quantity=d.get("quantity"),
            unit=d.get("unit"),
            location=loc,
            acquired_at=d.get("acquired_at"),
            acquired_from=d.get("acquired_from"),
            value=d.get("value"),
            currency=d.get("currency"),
            serial_number=d.get("serial_number"),
            barcode=d.get("barcode"),
            related_object_ids=d.get("related_object_ids", []),
        )


# ---------------------------------------------------------------------------
# InventoryCollection — create / update / response
# ---------------------------------------------------------------------------

class InventoryCollectionCreate(BaseModel):
    owner: str
    scope: str
    name: str
    description: Optional[str] = None
    item_ids: list[str] = []            # urn:cb:inventory_item:{uuid} IRIs


class InventoryCollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    item_ids: Optional[list[str]] = None
    scope: Optional[str] = None


class InventoryCollectionResponse(BaseModel):
    id: str
    type_slug: str = "inventory_collection"
    owner: str
    scope: str
    created_at: datetime
    updated_at: datetime
    source_node: Optional[str] = None
    content_hash: Optional[str] = None

    name: str
    description: Optional[str] = None
    item_ids: list[str] = []

    @classmethod
    def from_object_row(cls, obj) -> InventoryCollectionResponse:
        d = obj.capability_data or {}
        return cls(
            id=obj.id,
            owner=obj.owner_agent_id or obj.owner_group_id,
            scope=obj.scope,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            source_node=obj.source_node,
            content_hash=obj.content_hash,
            name=d.get("name", ""),
            description=d.get("description"),
            item_ids=d.get("item_ids", []),
        )
