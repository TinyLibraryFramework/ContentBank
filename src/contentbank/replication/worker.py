"""
Replication background worker.

Runs a pull sync cycle for each enabled peer on the configured interval.
Starts as an asyncio task during FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from contentbank.config import settings
from contentbank.db.database import AsyncSessionLocal
from contentbank.db.models import ReplicationPeer
from contentbank.replication.sync import pull_from_peer

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None


async def _sync_cycle() -> None:
    """One sync cycle: pull from all enabled peers."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(ReplicationPeer).where(
                    ReplicationPeer.sync_enabled == True  # noqa: E712
                )
            )
            peers = result.scalars().all()

            if not peers:
                return

            for peer in peers:
                try:
                    await pull_from_peer(db, peer)
                except Exception as e:
                    logger.exception(
                        f"Error during sync with peer {peer.peer_node_id}: {e}"
                    )

            await db.commit()
        except Exception as e:
            logger.exception(f"Sync cycle error: {e}")
            await db.rollback()


async def _worker_loop() -> None:
    """
    Main worker loop. Pulls each peer at its configured sync_interval_seconds.
    Uses the minimum interval across all peers as the tick rate,
    then checks per-peer whether it's due.
    """
    logger.info("Replication worker started")

    # Track last sync time per peer
    last_synced: dict[str, float] = {}

    import time

    while True:
        now = time.monotonic()

        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(ReplicationPeer).where(
                        ReplicationPeer.sync_enabled == True  # noqa: E712
                    )
                )
                peers = result.scalars().all()

                for peer in peers:
                    last = last_synced.get(peer.peer_node_id, 0.0)
                    due_in = peer.sync_interval_seconds - (now - last)
                    if due_in <= 0:
                        try:
                            await pull_from_peer(db, peer)
                            last_synced[peer.peer_node_id] = time.monotonic()
                        except Exception as e:
                            logger.exception(
                                f"Sync failed for {peer.peer_node_id}: {e}"
                            )

                await db.commit()
            except Exception as e:
                logger.exception(f"Worker loop DB error: {e}")
                await db.rollback()

        # Sleep for the shortest interval among all peers (min 10s)
        sleep_for = max(
            10,
            settings.replication_sync_interval_seconds // 4,
        )
        await asyncio.sleep(sleep_for)


def start_worker() -> None:
    """Start the replication worker as a background asyncio task."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(
            _worker_loop(),
            name="replication-worker",
        )
        logger.info("Replication worker task created")


def stop_worker() -> None:
    """Cancel the replication worker task on shutdown."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        logger.info("Replication worker stopped")
