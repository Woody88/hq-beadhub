"""Event publishing and streaming via Redis pub/sub.

This module provides the infrastructure for real-time event streaming:
- Event types for messages, escalations, and beads
- EventBus for publishing events to Redis pub/sub channels
- Helpers for SSE streaming
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)


class EventCategory(str, Enum):
    """Categories of events that can be streamed."""

    RESERVATION = "reservation"
    MESSAGE = "message"
    ESCALATION = "escalation"
    BEAD = "bead"


@dataclass
class Event:
    """Base class for all events."""

    workspace_id: str
    type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    project_slug: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @property
    def category(self) -> EventCategory:
        """Extract category from event type (e.g., 'message.delivered' -> 'message')."""
        return EventCategory(self.type.split(".")[0])


@dataclass
class ReservationAcquiredEvent(Event):
    """Event emitted when reservations are acquired."""

    type: str = field(default="reservation.acquired", init=False)
    paths: list[str] = field(default_factory=list)
    alias: str = ""
    ttl_seconds: int = 0
    bead_id: str | None = None
    reason: str | None = None
    exclusive: bool = True


@dataclass
class ReservationReleasedEvent(Event):
    """Event emitted when reservations are released."""

    type: str = field(default="reservation.released", init=False)
    paths: list[str] = field(default_factory=list)
    alias: str = ""


@dataclass
class ReservationRenewedEvent(Event):
    """Event emitted when reservation TTLs are extended."""

    type: str = field(default="reservation.renewed", init=False)
    paths: list[str] = field(default_factory=list)
    alias: str = ""
    ttl_seconds: int = 0


@dataclass
class MessageDeliveredEvent(Event):
    """Event emitted when a message is delivered to a workspace inbox."""

    type: str = field(default="message.delivered", init=False)
    message_id: str = ""
    from_workspace: str = ""
    from_alias: str = ""
    subject: str = ""
    priority: str = "normal"


@dataclass
class MessageAcknowledgedEvent(Event):
    """Event emitted when a message is acknowledged."""

    type: str = field(default="message.acknowledged", init=False)
    message_id: str = ""


@dataclass
class EscalationCreatedEvent(Event):
    """Event emitted when an escalation is created."""

    type: str = field(default="escalation.created", init=False)
    escalation_id: str = ""
    alias: str = ""
    subject: str = ""


@dataclass
class EscalationRespondedEvent(Event):
    """Event emitted when an escalation receives a response."""

    type: str = field(default="escalation.responded", init=False)
    escalation_id: str = ""
    response: str = ""


@dataclass
class BeadStatusChangedEvent(Event):
    """Event emitted when a bead's status changes."""

    type: str = field(default="bead.status_changed", init=False)
    project_id: str = ""
    bead_id: str = ""
    repo: str = ""
    old_status: str = ""
    new_status: str = ""


# =============================================================================
# Chat Events (for real-time agent chat sessions)
# =============================================================================


@dataclass
class ChatEvent:
    """Base class for chat session events.

    Chat events are scoped to a session, not a workspace.
    """

    session_id: str
    type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class ChatMessageEvent(ChatEvent):
    """Event emitted when a message is sent in a chat session.

    Sessions are persistent and do not require explicit join/leave state.
    """

    type: str = field(default="message", init=False)
    message_id: str = ""
    from_agent: str = ""
    body: str = ""
    sender_leaving: bool = False  # True when sender left the conversation
    hang_on: bool = False  # True when sender requests more time
    extends_wait_seconds: int = 0  # How long to extend wait (for hang_on)


@dataclass
class ChatReadReceiptEvent(ChatEvent):
    """Event emitted when a participant reads messages in a chat session.

    Notifies the original sender that their message was read, allowing their
    CLI to extend the wait timeout.
    """

    type: str = field(default="read_receipt", init=False)
    reader: str = ""  # workspace_id of the reader
    reader_alias: str = ""  # alias of the reader
    up_to_message_id: str = ""  # messages read up to this ID
    extends_wait_seconds: int = 0  # How long to extend the sender's wait


def _channel_name(workspace_id: str) -> str:
    """Generate Redis channel name for a workspace."""
    return f"events:{workspace_id}"


def _chat_channel_name(session_id: str) -> str:
    """Generate Redis channel name for a chat session."""
    return f"chat:{session_id}"


async def publish_event(redis: Redis, event: Event) -> int:
    """Publish an event to the workspace's Redis pub/sub channel.

    Args:
        redis: Redis client
        event: Event to publish

    Returns:
        Number of subscribers that received the message
    """
    channel = _channel_name(event.workspace_id)
    message = event.to_json()
    count = await redis.publish(channel, message)
    logger.debug(f"Published {event.type} to {channel}, {count} subscribers")
    return count


async def stream_events(
    redis: Redis,
    workspace_id: str,
    event_types: Optional[set[str]] = None,
    keepalive_seconds: int = 30,
) -> AsyncIterator[str]:
    """Stream events for a workspace as SSE-formatted strings.

    Args:
        redis: Redis client
        workspace_id: Workspace to stream events for
        event_types: Optional set of event categories to filter (e.g., {'message', 'bead'})
                     If None, all events are streamed.
        keepalive_seconds: Seconds between keepalive comments

    Yields:
        SSE-formatted event strings (e.g., "data: {...}\\n\\n")
    """
    async for event in stream_events_multi(redis, [workspace_id], event_types, keepalive_seconds):
        yield event


async def stream_events_multi(
    redis: Redis,
    workspace_ids: list[str],
    event_types: Optional[set[str]] = None,
    keepalive_seconds: int = 30,
    check_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
) -> AsyncIterator[str]:
    """Stream events for multiple workspaces as SSE-formatted strings.

    Args:
        redis: Redis client
        workspace_ids: List of workspace IDs to stream events for
        event_types: Optional set of event categories to filter (e.g., {'message', 'bead'})
                     If None, all events are streamed.
        keepalive_seconds: Seconds between keepalive comments
        check_disconnected: Optional async callback to check if client has disconnected.
                           When provided and returns True, the stream ends cleanly.

    Yields:
        SSE-formatted event strings (e.g., "data: {...}\\n\\n")
    """
    channels = [_channel_name(ws_id) for ws_id in workspace_ids]

    # Empty workspace list: send keepalives for a limited time.
    # This handles new projects with no workspaces yet while preventing
    # resource leaks if disconnect detection fails.
    if not channels:
        max_duration_seconds = 5 * 60  # 5 minutes
        max_keepalives = max_duration_seconds // keepalive_seconds
        keepalive_count = 0

        while keepalive_count < max_keepalives:
            # Check for client disconnect
            if check_disconnected and await check_disconnected():
                logger.debug("Client disconnected (empty workspace list)")
                return
            await asyncio.sleep(keepalive_seconds)
            yield ": keepalive\n\n"
            keepalive_count += 1

        logger.debug("Empty workspace stream reached max duration, closing")
        return

    pubsub: PubSub = redis.pubsub()

    try:
        await pubsub.subscribe(*channels)
        logger.debug(f"Subscribed to {len(channels)} channels")

        last_keepalive = asyncio.get_event_loop().time()

        while True:
            # Check for messages with timeout for keepalive
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=keepalive_seconds,
                )
            except asyncio.TimeoutError:
                message = None

            # Check for client disconnect
            if check_disconnected and await check_disconnected():
                logger.debug(f"Client disconnected, ending stream for {len(channels)} channels")
                return

            current_time = asyncio.get_event_loop().time()

            if message is not None and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                # Parse event to check category filter
                try:
                    event_data = json.loads(data)
                    event_category = event_data.get("type", "").split(".")[0]

                    # Apply filter if specified
                    if event_types is None or event_category in event_types:
                        yield f"data: {data}\n\n"
                        last_keepalive = current_time
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in event: {data}")
                    continue

            # Send keepalive comment if needed
            if current_time - last_keepalive >= keepalive_seconds:
                yield ": keepalive\n\n"
                last_keepalive = current_time

    except asyncio.CancelledError:
        logger.debug(f"Stream cancelled for {len(channels)} channels")
        raise
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
        logger.debug(f"Unsubscribed from {len(channels)} channels")


async def publish_chat_event(redis: Redis, event: ChatEvent) -> int:
    """Publish a chat event to the session's Redis pub/sub channel.

    Args:
        redis: Redis client
        event: Chat event to publish

    Returns:
        Number of subscribers that received the message
    """
    channel = _chat_channel_name(event.session_id)
    message = event.to_json()
    count = await redis.publish(channel, message)
    logger.debug(f"Published chat {event.type} to {channel}, {count} subscribers")
    return count


def _chat_waiting_key(session_id: str) -> str:
    """Redis key for tracking workspaces waiting in a chat session."""
    return f"chat:waiting:{session_id}"


def _chat_deadline_key(session_id: str) -> str:
    """Redis key for tracking workspace deadlines in a chat session.

    Stores deadline timestamps so we can show time remaining to other participants.
    """
    return f"chat:deadline:{session_id}"


async def _ensure_waiting_key_zset(redis: Redis, waiting_key: str, keep_ttl: bool = True) -> None:
    """Ensure the chat waiting key uses a ZSET (member -> last_seen timestamp).

    If the key exists with an unexpected Redis type, ZSET operations will raise
    WRONGTYPE. This function replaces the key with a ZSET (best-effort).

    This function is best-effort and safe to call on hot paths.
    """
    try:
        key_type = await redis.type(waiting_key)
    except Exception:
        logger.warning("Failed to read Redis key type for waiting_key=%s", waiting_key, exc_info=True)
        return

    # redis-py returns bytes for TYPE.
    if isinstance(key_type, bytes):
        key_type = key_type.decode("utf-8", errors="ignore")

    if key_type in ("none", ""):
        return
    if key_type == "zset":
        return

    ttl = None
    if keep_ttl:
        try:
            ttl = await redis.ttl(waiting_key)
        except Exception:
            logger.warning("Failed to read Redis TTL for waiting_key=%s", waiting_key, exc_info=True)
            ttl = None

    if key_type == "set":
        try:
            members = await redis.smembers(waiting_key)
        except Exception:
            logger.warning("Failed to read Redis set members for waiting_key=%s", waiting_key, exc_info=True)
            members = set()

        try:
            await redis.delete(waiting_key)
        except Exception:
            logger.warning("Failed to delete Redis key waiting_key=%s for type migration", waiting_key, exc_info=True)
            return

        mapping: dict[str, float] = {}
        now = time.time()
        for m in members:
            if isinstance(m, bytes):
                m = m.decode("utf-8", errors="ignore")
            mapping[str(m)] = now

        if mapping:
            try:
                await redis.zadd(waiting_key, mapping)
            except Exception:
                logger.warning("Failed to write Redis zset waiting_key=%s for type migration", waiting_key, exc_info=True)
                return

        if ttl is not None and ttl > 0:
            try:
                await redis.expire(waiting_key, ttl)
            except Exception:
                logger.warning(
                    "Failed to restore Redis TTL for waiting_key=%s after type migration",
                    waiting_key,
                    exc_info=True,
                )
        return

    # Unknown type; safest is to delete it to avoid crashing endpoints.
    try:
        await redis.delete(waiting_key)
    except Exception:
        logger.warning("Failed to delete Redis key waiting_key=%s with unknown type", waiting_key, exc_info=True)


async def is_workspace_waiting(
    redis: Redis,
    session_id: str,
    workspace_id: str,
    max_age_seconds: int = 90,
) -> bool:
    """Check if a workspace is currently waiting (connected to SSE) in a session.

    We track a per-workspace "last seen" timestamp in a Redis sorted set.
    This avoids false positives when the Redis key TTL is refreshed by other
    connected workspaces (stale members can no longer stick indefinitely).
    """
    waiting_key = _chat_waiting_key(session_id)
    await _ensure_waiting_key_zset(redis, waiting_key)
    try:
        score = await redis.zscore(waiting_key, workspace_id)
    except ResponseError as e:
        if "WRONGTYPE" in str(e):
            await _ensure_waiting_key_zset(redis, waiting_key)
            score = await redis.zscore(waiting_key, workspace_id)
        else:
            raise
    if score is None:
        return False
    now = time.time()
    if float(score) < now - max_age_seconds:
        await redis.zrem(waiting_key, workspace_id)
        # Best-effort: clean up stale deadline too.
        try:
            await redis.hdel(_chat_deadline_key(session_id), workspace_id)
        except Exception:
            logger.warning(
                "Failed to delete stale chat deadline session_id=%s workspace_id=%s",
                session_id,
                workspace_id,
                exc_info=True,
            )
        return False
    return True


async def get_workspace_deadline(
    redis: Redis,
    session_id: str,
    workspace_id: str,
) -> Optional[datetime]:
    """Get the deadline for a workspace waiting in a chat session.

    Returns the deadline timestamp if the workspace has one set, or None if no
    deadline is stored.

    Args:
        redis: Redis client
        session_id: Chat session ID
        workspace_id: Workspace ID to check

    Returns:
        Deadline as datetime (UTC) or None if not set
    """
    deadline_key = _chat_deadline_key(session_id)
    try:
        deadline_str = await redis.hget(deadline_key, workspace_id)
        if deadline_str:
            if isinstance(deadline_str, bytes):
                deadline_str = deadline_str.decode("utf-8")
            return datetime.fromisoformat(deadline_str)
    except Exception:
        logger.warning(
            "Failed to get workspace deadline session_id=%s workspace_id=%s",
            session_id,
            workspace_id,
            exc_info=True,
        )
    return None


async def extend_workspace_deadline(
    redis: Redis,
    session_id: str,
    workspace_id: str,
    extends_seconds: int,
) -> Optional[datetime]:
    """Extend a workspace's stored wait deadline for a chat session.

    This only updates Redis metadata used for time-remaining displays. The client
    must still extend its own local wait timeout to avoid disconnecting.

    Returns the new deadline when one exists and was updated, otherwise None.
    """
    if extends_seconds <= 0:
        return None

    deadline_key = _chat_deadline_key(session_id)
    current = await get_workspace_deadline(redis, session_id, workspace_id)
    if current is None:
        return None

    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    new_deadline = current + timedelta(seconds=extends_seconds)

    try:
        await redis.hset(deadline_key, workspace_id, new_deadline.isoformat())
        # Keep the deadline hash alive while the waiting zset is alive.
        waiting_ttl = await redis.ttl(_chat_waiting_key(session_id))
        if waiting_ttl and waiting_ttl > 0:
            await redis.expire(deadline_key, waiting_ttl)
    except Exception:
        logger.warning(
            "Failed to extend workspace deadline session_id=%s workspace_id=%s",
            session_id,
            workspace_id,
            exc_info=True,
        )
        return None

    return new_deadline


async def stream_chat_events(
    redis: Redis,
    session_id: str,
    workspace_id: str,
    keepalive_seconds: int = 30,
    check_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
    deadline: Optional[datetime] = None,
) -> AsyncIterator[str]:
    """Stream chat events for a session as SSE-formatted strings.

    Tracks workspace connection state in Redis to enable "waiting" detection.
    When workspace connects, it's added to the waiting set.
    When workspace disconnects (timeout, reply received, crash), it's removed.

    Args:
        redis: Redis client
        session_id: Chat session to stream events for
        workspace_id: Workspace ID of the connecting client
        keepalive_seconds: Seconds between keepalive comments
        check_disconnected: Optional async callback to check if client has disconnected.
                           When provided and returns True, the stream ends cleanly.
        deadline: Optional deadline timestamp for this workspace's wait.
                  If provided, stored in Redis so other participants can see time remaining.

    Yields:
        SSE-formatted event strings with event type (e.g., "event: message\\ndata: {...}\\n\\n")
    """
    channel = _chat_channel_name(session_id)
    waiting_key = _chat_waiting_key(session_id)
    deadline_key = _chat_deadline_key(session_id)
    pubsub: PubSub = redis.pubsub()

    # TTL for waiting set - 3x keepalive to handle missed refreshes
    waiting_ttl = keepalive_seconds * 3

    try:
        await _ensure_waiting_key_zset(redis, waiting_key)

        # Track that this workspace is waiting for a reply.
        # Use a per-workspace heartbeat timestamp so stale entries decay even
        # if other workspaces keep the key alive.
        await redis.zadd(waiting_key, {workspace_id: time.time()})
        await redis.expire(waiting_key, waiting_ttl)

        # Store deadline if provided
        if deadline:
            await redis.hset(deadline_key, workspace_id, deadline.isoformat())
            await redis.expire(deadline_key, waiting_ttl)

        logger.debug(f"Workspace {workspace_id} now waiting in session {session_id}")

        await pubsub.subscribe(channel)
        logger.debug(f"Subscribed to chat channel {channel}")

        last_keepalive = asyncio.get_event_loop().time()

        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=keepalive_seconds,
                )
            except asyncio.TimeoutError:
                message = None

            # Check for client disconnect
            if check_disconnected and await check_disconnected():
                logger.debug(f"Client disconnected, ending chat stream for {channel}")
                return

            current_time = asyncio.get_event_loop().time()

            if message is not None and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                try:
                    event_data = json.loads(data)
                    event_type = event_data.get("type", "message")
                    # SSE format with event type for client-side event handling
                    yield f"event: {event_type}\ndata: {data}\n\n"
                    last_keepalive = current_time
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in chat event: {data}")
                    continue

            if current_time - last_keepalive >= keepalive_seconds:
                yield ": keepalive\n\n"
                last_keepalive = current_time
                # Refresh heartbeat + TTL to prevent expiration while connected
                await _ensure_waiting_key_zset(redis, waiting_key)
                await redis.zadd(waiting_key, {workspace_id: time.time()})
                await redis.expire(waiting_key, waiting_ttl)
                # Also refresh deadline TTL (key may exist even if this stream didn't set it).
                try:
                    await redis.expire(deadline_key, waiting_ttl)
                except Exception:
                    logger.warning(
                        "Failed to refresh chat deadline TTL session_id=%s workspace_id=%s",
                        session_id,
                        workspace_id,
                        exc_info=True,
                    )

    except asyncio.CancelledError:
        logger.debug(f"Chat stream cancelled for {channel}")
        raise
    finally:
        # Remove from waiting set - workspace is no longer waiting
        await redis.zrem(waiting_key, workspace_id)
        # Also remove deadline
        await redis.hdel(deadline_key, workspace_id)
        logger.debug(f"Workspace {workspace_id} no longer waiting in session {session_id}")

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        logger.debug(f"Unsubscribed from chat channel {channel}")
