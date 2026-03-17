"""
Calendar Capability routes.

POST   /calendar/events         create event
GET    /calendar/events/{id}    get event
PATCH  /calendar/events/{id}    update event
DELETE /calendar/events/{id}    delete event
GET    /calendar/events         list events (filterable by date range)
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from contentbank.db.database import get_db
from contentbank.core import storage as store
from contentbank.core.models import Page
from contentbank.auth.dependencies import require_agent
from contentbank.capabilities.calendar.models import (
    CalendarEventCreate,
    CalendarEventUpdate,
    CalendarEventResponse,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])

TYPE_SLUG = "calendar_event"


def _to_capability_data(body: CalendarEventCreate | CalendarEventUpdate) -> dict:
    """Extract calendar-specific fields into the capability_data dict."""
    d = {}
    fields = [
        "title", "description", "start_at", "end_at", "all_day",
        "location", "status", "attendee_ids", "related_object_ids",
    ]
    for f in fields:
        val = getattr(body, f, None)
        if val is not None:
            # Serialize datetimes to ISO strings for JSON storage
            if isinstance(val, datetime):
                d[f] = val.isoformat()
            else:
                d[f] = val

    if getattr(body, "recurrence", None) is not None:
        d["recurrence"] = body.recurrence.model_dump(exclude_none=True)

    reminders = getattr(body, "reminders", None)
    if reminders is not None:
        d["reminders"] = [r.model_dump(exclude_none=True) for r in reminders]

    return d


@router.post("/events", response_model=CalendarEventResponse, status_code=201)
async def create_event(
    body: CalendarEventCreate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Create a calendar event. SHACL-validated before write."""
    try:
        obj = await store.objects.create_object(
            db,
            type_slug=TYPE_SLUG,
            owner_id=body.owner,
            scope=body.scope,
            capability_data=_to_capability_data(body),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return CalendarEventResponse.from_object_row(obj)


@router.get("/events/{event_id}", response_model=CalendarEventResponse)
async def get_event(
    event_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Get a calendar event. Scope access enforced."""
    try:
        obj = await store.objects.get_object(
            db,
            obj_id=event_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Event not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")

    if obj.type_slug != TYPE_SLUG:
        raise HTTPException(status_code=404, detail="Event not found")

    return CalendarEventResponse.from_object_row(obj)


@router.patch("/events/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: str,
    body: CalendarEventUpdate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Update a calendar event. Owner only."""
    try:
        obj = await store.objects.update_object(
            db,
            obj_id=event_id,
            requesting_agent_id=requesting_agent_id,
            metadata=_to_capability_data(body),
            scope=body.scope,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Event not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return CalendarEventResponse.from_object_row(obj)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Delete a calendar event. Owner only."""
    try:
        await store.objects.delete_object(
            db,
            obj_id=event_id,
            requesting_agent_id=requesting_agent_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Event not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/events", response_model=Page)
async def list_events(
    owner: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("-updated_at"),
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """List calendar events visible to the requesting agent."""
    objects, next_cursor = await store.objects.list_objects(
        db,
        requesting_agent_id=requesting_agent_id,
        type_slug=TYPE_SLUG,
        owner=owner,
        scope=scope,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )

    return Page(
        items=[CalendarEventResponse.from_object_row(o) for o in objects],
        cursor=next_cursor,
        has_more=next_cursor is not None,
    )
