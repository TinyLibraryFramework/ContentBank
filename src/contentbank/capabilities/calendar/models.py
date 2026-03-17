"""
Pydantic models for the Calendar Capability.
Maps to shapes/capability/calendar/shapes.ttl — tlcal: namespace.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, model_validator


# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------

class ReminderModel(BaseModel):
    minutes_before: int  # >= 0
    method: Optional[Literal["notification", "email", "mesh"]] = "notification"


# ---------------------------------------------------------------------------
# Recurrence Rule
# ---------------------------------------------------------------------------

class RecurrenceRuleModel(BaseModel):
    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    interval: Optional[int] = None          # every N frequencies
    until: Optional[datetime] = None        # end datetime (exclusive with count)
    count: Optional[int] = None             # end after N occurrences
    by_day: Optional[list[str]] = None      # ["MO", "WE", "FR"]

    @model_validator(mode="after")
    def until_and_count_exclusive(self) -> RecurrenceRuleModel:
        if self.until is not None and self.count is not None:
            raise ValueError("until and count are mutually exclusive")
        return self


# ---------------------------------------------------------------------------
# Calendar Event — create / update
# ---------------------------------------------------------------------------

class CalendarEventCreate(BaseModel):
    """Input for POST /calendar/events"""
    owner: str
    scope: str

    title: str
    description: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    location: Optional[str] = None
    status: Optional[Literal["tentative", "confirmed", "cancelled"]] = "confirmed"
    attendee_ids: list[str] = []            # urn:cb:agent:{uuid} IRIs
    recurrence: Optional[RecurrenceRuleModel] = None
    reminders: list[ReminderModel] = []
    related_object_ids: list[str] = []      # IRIs of related ContentBank objects


class CalendarEventUpdate(BaseModel):
    """Input for PATCH /calendar/events/{id}"""
    title: Optional[str] = None
    description: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    location: Optional[str] = None
    status: Optional[Literal["tentative", "confirmed", "cancelled"]] = None
    attendee_ids: Optional[list[str]] = None
    recurrence: Optional[RecurrenceRuleModel] = None
    reminders: Optional[list[ReminderModel]] = None
    related_object_ids: Optional[list[str]] = None
    scope: Optional[str] = None


# ---------------------------------------------------------------------------
# Calendar Event — response
# ---------------------------------------------------------------------------

class CalendarEventResponse(BaseModel):
    """Full object response for a CalendarEvent."""
    id: str
    type_slug: str = "calendar_event"
    owner: str
    scope: str
    created_at: datetime
    updated_at: datetime
    source_node: Optional[str] = None
    content_hash: Optional[str] = None

    # Capability-specific fields
    title: str
    description: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    location: Optional[str] = None
    status: Optional[str] = None
    attendee_ids: list[str] = []
    recurrence: Optional[RecurrenceRuleModel] = None
    reminders: list[ReminderModel] = []
    related_object_ids: list[str] = []

    @classmethod
    def from_object_row(cls, obj) -> CalendarEventResponse:
        d = obj.capability_data or {}
        return cls(
            id=obj.id,
            owner=obj.owner_agent_id or obj.owner_group_id,
            scope=obj.scope,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            source_node=obj.source_node,
            content_hash=obj.content_hash,
            title=d.get("title", ""),
            description=d.get("description"),
            start_at=d.get("start_at"),
            end_at=d.get("end_at"),
            all_day=d.get("all_day"),
            location=d.get("location"),
            status=d.get("status"),
            attendee_ids=d.get("attendee_ids", []),
            recurrence=RecurrenceRuleModel(**d["recurrence"])
                       if d.get("recurrence") else None,
            reminders=[ReminderModel(**r) for r in d.get("reminders", [])],
            related_object_ids=d.get("related_object_ids", []),
        )
