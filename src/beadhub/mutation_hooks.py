"""Translate aweb mutation hooks into beadhub SSE events.

aweb fires app.state.on_mutation(event_type, context) after successful
mutations. This module registers a handler that publishes corresponding
Event dataclasses to Redis pub/sub for the dashboard SSE stream.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from .events import (
    ChatMessageEvent,
    MessageAcknowledgedEvent,
    MessageDeliveredEvent,
    ReservationAcquiredEvent,
    ReservationReleasedEvent,
    publish_event,
)

logger = logging.getLogger(__name__)


def create_mutation_handler(redis: Redis):
    """Create an on_mutation callback that publishes SSE events.

    The returned async callable matches aweb's hook signature:
        async def on_mutation(event_type: str, context: dict) -> None
    """

    async def on_mutation(event_type: str, context: dict) -> None:
        try:
            event = _translate(event_type, context)
            if event is None:
                return
            if not event.workspace_id:
                logger.warning("Skipping %s event: no workspace_id in context", event_type)
                return
            await publish_event(redis, event)
        except Exception:
            logger.warning("Failed to publish event for %s", event_type, exc_info=True)

    return on_mutation


def _translate(event_type: str, ctx: dict):
    """Map an aweb mutation event to a beadhub Event dataclass."""

    if event_type == "message.sent":
        return MessageDeliveredEvent(
            workspace_id=ctx.get("to_agent_id", ""),
            message_id=ctx.get("message_id", ""),
            from_workspace=ctx.get("from_agent_id", ""),
            subject=ctx.get("subject", ""),
        )

    if event_type == "message.acknowledged":
        return MessageAcknowledgedEvent(
            workspace_id=ctx.get("agent_id", ""),
            message_id=ctx.get("message_id", ""),
        )

    if event_type == "chat.message_sent":
        return ChatMessageEvent(
            workspace_id=ctx.get("from_agent_id", ""),
            session_id=ctx.get("session_id", ""),
            message_id=ctx.get("message_id", ""),
        )

    if event_type == "reservation.acquired":
        return ReservationAcquiredEvent(
            workspace_id=ctx.get("holder_agent_id", ""),
            paths=[ctx["resource_key"]] if ctx.get("resource_key") else [],
            ttl_seconds=ctx.get("ttl_seconds", 0),
        )

    if event_type == "reservation.released":
        return ReservationReleasedEvent(
            workspace_id=ctx.get("holder_agent_id", ""),
            paths=[ctx["resource_key"]] if ctx.get("resource_key") else [],
        )

    return None
