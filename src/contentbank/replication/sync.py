"""
Replication sync logic.

Outbound: pull events from a peer since last_seen_seq.
Inbound:  serve events to peers requesting our log.
Causal:   hold writes with ScopeGroup dependencies until the
          dependency is present in the local log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from contentbank.config import settings
from contentbank.db.models import (
    ReplicationLog, ReplicationPeerState, ReplicationPeer,
    Object, BlobAttachment, ScopeGroup,
)
from contentbank.auth.tokens import issue_node_token
from contentbank.core.storage.objects import create_object

logger = logging.getLogger(__name__)

# In-memory causal hold queue: list of event dicts waiting on a dependency
_causal_hold: list[dict] = []


# ---------------------------------------------------------------------------
# Serve: build sync response for an inbound peer pull
# ---------------------------------------------------------------------------

async def get_events_since(
    db: AsyncSession,
    since_seq: int,
    limit: int = 500,
) -> tuple[list[dict], bool]:
    """
    Return replication log events since since_seq.
    Returns (events, has_more).
    Each event includes the full object payload for insert/update.
    """
    result = await db.execute(
        select(ReplicationLog)
        .where(ReplicationLog.seq > since_seq)
        .order_by(ReplicationLog.seq)
        .limit(limit + 1)
    )
    rows = result.scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    events = []
    for log_row in rows:
        event = {
            "node_id": log_row.node_id,
            "node_seq": log_row.node_seq,
            "object_id": log_row.object_id,
            "change_type": log_row.change_type,
            "updated_at": log_row.updated_at.isoformat(),
            "scope_group_dep_node": log_row.scope_group_dep_node,
            "scope_group_dep_seq": log_row.scope_group_dep_seq,
            "object_payload": None,
        }

        if log_row.change_type in ("insert", "update"):
            obj_result = await db.execute(
                select(Object).where(Object.id == log_row.object_id)
            )
            obj = obj_result.scalar_one_or_none()
            if obj:
                blobs_result = await db.execute(
                    select(BlobAttachment).where(
                        BlobAttachment.object_id == obj.id
                    )
                )
                blobs = blobs_result.scalars().all()
                event["object_payload"] = {
                    "id": obj.id,
                    "type_slug": obj.type_slug,
                    "owner_agent_id": obj.owner_agent_id,
                    "owner_group_id": obj.owner_group_id,
                    "scope": obj.scope,
                    "created_at": obj.created_at.isoformat(),
                    "updated_at": obj.updated_at.isoformat(),
                    "source_node": obj.source_node,
                    "content_hash": obj.content_hash,
                    "capability_data": obj.capability_data,
                    "blobs": [
                        {
                            "cid": b.cid,
                            "mime_type": b.mime_type,
                            "blob_role": b.blob_role,
                            "byte_size": b.byte_size,
                            "content_hash": b.content_hash,
                        }
                        for b in blobs
                    ],
                }

        events.append(event)

    return events, has_more


# ---------------------------------------------------------------------------
# Receive: apply events from a peer pull response
# ---------------------------------------------------------------------------

async def apply_events(
    db: AsyncSession,
    events: list[dict],
) -> int:
    """
    Apply a batch of replication events received from a peer.
    Returns count of events applied (held events are not counted).
    """
    applied = 0

    for event in events:
        dep_node = event.get("scope_group_dep_node")
        dep_seq = event.get("scope_group_dep_seq")

        if dep_node and dep_seq:
            # Check if dependency is already in our local log
            dep_result = await db.execute(
                select(ReplicationLog).where(
                    and_(
                        ReplicationLog.node_id == dep_node,
                        ReplicationLog.node_seq >= dep_seq,
                    )
                ).limit(1)
            )
            if dep_result.scalar_one_or_none() is None:
                logger.debug(
                    f"Holding event {event['object_id']} — "
                    f"waiting for dep ({dep_node}, seq>={dep_seq})"
                )
                _causal_hold.append(event)
                continue

        await _apply_single_event(db, event)
        applied += 1

    # Retry held events after applying new ones
    applied += await _flush_causal_hold(db)
    return applied


async def _apply_single_event(db: AsyncSession, event: dict) -> None:
    """Apply one replication event to local storage."""
    change_type = event["change_type"]
    object_id = event["object_id"]
    payload = event.get("object_payload")

    if change_type == "delete":
        obj_result = await db.execute(
            select(Object).where(Object.id == object_id)
        )
        obj = obj_result.scalar_one_or_none()
        if obj:
            await db.delete(obj)

    elif change_type in ("insert", "update") and payload:
        obj_result = await db.execute(
            select(Object).where(Object.id == object_id)
        )
        existing = obj_result.scalar_one_or_none()

        p_updated = datetime.fromisoformat(payload["updated_at"])
        p_created = datetime.fromisoformat(payload["created_at"])

        if existing is None:
            # Insert new object — bypass SHACL for replication ingestion
            await create_object(
                db,
                type_slug=payload["type_slug"],
                owner_id=payload["owner_agent_id"] or payload["owner_group_id"],
                scope=payload["scope"],
                capability_data=payload.get("capability_data") or {},
                blobs=payload.get("blobs", []),
                source_node=payload.get("source_node"),
                validate=False,
            )
        else:
            # Conflict resolution: last-write-wins by updated_at, node_id tiebreaker
            if (p_updated, event["node_id"]) > (
                existing.updated_at, existing.source_node or ""
            ):
                existing.type_slug = payload["type_slug"]
                existing.owner_agent_id = payload["owner_agent_id"]
                existing.owner_group_id = payload["owner_group_id"]
                existing.scope = payload["scope"]
                existing.updated_at = p_updated
                existing.source_node = payload.get("source_node")
                existing.content_hash = payload.get("content_hash")
                existing.capability_data = payload.get("capability_data") or {}
                # Replace blobs
                blobs_result = await db.execute(
                    select(BlobAttachment).where(
                        BlobAttachment.object_id == object_id
                    )
                )
                for blob in blobs_result.scalars().all():
                    await db.delete(blob)
                for blob_data in payload.get("blobs", []):
                    import uuid
                    from contentbank.db.models import BlobAttachment as BA
                    db.add(BA(
                        id=f"urn:cb:blob:{uuid.uuid4()}",
                        object_id=object_id,
                        **blob_data,
                    ))
            else:
                logger.debug(
                    f"Skipping stale update for {object_id} — "
                    f"local version wins"
                )

    # Record in local replication log
    updated_at = datetime.fromisoformat(event["updated_at"])
    db.add(ReplicationLog(
        node_id=event["node_id"],
        node_seq=event["node_seq"],
        object_id=object_id,
        change_type=change_type,
        updated_at=updated_at,
        scope_group_dep_node=event.get("scope_group_dep_node"),
        scope_group_dep_seq=event.get("scope_group_dep_seq"),
    ))
    await db.flush()


async def _flush_causal_hold(db: AsyncSession) -> int:
    """Re-attempt held events. Returns count applied."""
    if not _causal_hold:
        return 0

    applied = 0
    remaining = []

    for event in _causal_hold:
        dep_node = event["scope_group_dep_node"]
        dep_seq = event["scope_group_dep_seq"]

        dep_result = await db.execute(
            select(ReplicationLog).where(
                and_(
                    ReplicationLog.node_id == dep_node,
                    ReplicationLog.node_seq >= dep_seq,
                )
            ).limit(1)
        )
        if dep_result.scalar_one_or_none() is not None:
            await _apply_single_event(db, event)
            applied += 1
        else:
            remaining.append(event)

    _causal_hold.clear()
    _causal_hold.extend(remaining)
    return applied


# ---------------------------------------------------------------------------
# Pull: fetch events from a single peer
# ---------------------------------------------------------------------------

async def pull_from_peer(
    db: AsyncSession,
    peer: ReplicationPeer,
) -> int:
    """
    Pull replication events from a peer node.
    Returns count of events applied.
    """
    # Get last seen seq for this peer
    state_result = await db.execute(
        select(ReplicationPeerState).where(
            ReplicationPeerState.peer_node_id == peer.peer_node_id
        )
    )
    state = state_result.scalar_one_or_none()
    since_seq = state.last_seen_seq if state else 0

    token = issue_node_token()
    url = f"{peer.endpoint.rstrip('/')}/api/v1/replication/sync"
    params = {"since": since_seq, "limit": 500}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.warning(f"Sync pull from {peer.peer_node_id} failed: {e}")
        return 0

    events = data.get("events", [])
    applied = await apply_events(db, events)

    # Update peer state
    if events:
        max_seq = max(e["node_seq"] for e in events)
        now = datetime.now(timezone.utc)
        if state is None:
            db.add(ReplicationPeerState(
                peer_node_id=peer.peer_node_id,
                last_seen_seq=max_seq,
                last_sync_at=now,
            ))
        else:
            state.last_seen_seq = max(state.last_seen_seq, max_seq)
            state.last_sync_at = now
        await db.flush()

    logger.info(
        f"Sync from {peer.peer_node_id}: "
        f"{len(events)} events received, {applied} applied"
    )
    return applied
