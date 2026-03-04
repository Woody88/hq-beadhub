import type Redis from "ioredis";
import type { TextChannel, ThreadChannel, WebhookClient } from "discord.js";
import type { BeadHubEvent, ChatMessageEvent } from "./types.js";
import type { SessionMap } from "./session-map.js";
import { config } from "./config.js";
import { getSessionMessages, getSessionMessagesWithKey, getProjectRepos } from "./beadhub-client.js";
import { sendAsAgent } from "./discord-sender.js";
import { stopTypingIndicator } from "./discord-listener.js";

/** Set of message_ids we've already relayed (echo suppression + dedup). */
const recentlyRelayed = new Set<string>();

export function markRelayed(messageId: string, ttlMs: number): void {
  recentlyRelayed.add(messageId);
  setTimeout(() => recentlyRelayed.delete(messageId), ttlMs);
}

export function wasRelayed(messageId: string): boolean {
  return recentlyRelayed.has(messageId);
}

/**
 * Subscribe to all workspace event channels via PSUBSCRIBE events:*
 * and relay chat.message_sent events to Discord.
 *
 * The `cmdRedis` client is used for regular commands (RPUSH to orchestrator inbox).
 * A duplicate is created internally for PSUBSCRIBE.
 *
 * `ordisChannel` (optional) is the #ordis TextChannel used to create worker spin-up
 * threads. When provided, BeadHub chat sessions involving neo/hawk are mirrored into
 * a dedicated thread created under a "🤖 Spinning up <worker>" message in #ordis.
 */
/** Optional ordis webhook for posting to #ordis channel directly */
export interface OrdisWebhookConfig {
  webhookUrl: string;
  controlPlaneProjectId: string;
}

let ordisWebhookConfig: OrdisWebhookConfig | null = null;

export function setOrdisWebhookConfig(cfg: OrdisWebhookConfig): void {
  ordisWebhookConfig = cfg;
}

export async function startRedisListener(
  cmdRedis: Redis,
  channel: TextChannel,
  webhook: WebhookClient,
  sessionMap: SessionMap,
  echoTtlMs: number,
  bridgeAlias: string,
  ordisChannel?: TextChannel,
): Promise<void> {
  // ioredis requires a duplicate client for subscriptions
  const sub = cmdRedis.duplicate();

  sub.on("error", (err) => {
    console.error("[redis] Subscription error:", err.message);
  });

  await sub.psubscribe("events:*");
  console.log("[redis] PSUBSCRIBE events:* — listening for chat events");

  sub.on("pmessage", async (_pattern: string, _chan: string, message: string) => {
    try {
      const event: BeadHubEvent = JSON.parse(message);
      if (event.type !== "chat.message_sent") return;

      const chatEvent = event as unknown as ChatMessageEvent;

      // Skip messages sent by the bridge itself (human Discord replies relayed to BeadHub)
      if (chatEvent.from_alias === bridgeAlias) return;

      await handleChatMessage(chatEvent, cmdRedis, channel, webhook, sessionMap, echoTtlMs, ordisChannel);
    } catch (err) {
      console.error("[redis] Error handling event:", err);
    }
  });
}

/**
 * Worker agent aliases. Chat sessions involving these aliases are mirrored into
 * a dedicated thread in #ordis (under a spin-up message), rather than #agent-comms.
 */
const WORKER_AGENTS = new Set(["neo", "hawk"]);

/** Extract a bead ID (e.g. "hq-beadhub-295") from a message body for the thread name. */
function extractBeadId(body: string): string | null {
  const match = body.match(/\b([a-z]+-[a-z]+-\d+)\b/i);
  return match ? match[1] : null;
}

async function handleChatMessage(
  event: ChatMessageEvent,
  cmdRedis: Redis,
  channel: TextChannel,
  webhook: WebhookClient,
  sessionMap: SessionMap,
  echoTtlMs: number,
  ordisChannel?: TextChannel,
): Promise<void> {
  // Dedup: same chat message fires on each participant's channel
  if (wasRelayed(event.message_id)) return;
  markRelayed(event.message_id, echoTtlMs);

  const involvesWorker =
    WORKER_AGENTS.has(event.from_alias) ||
    event.to_aliases.some((a) => WORKER_AGENTS.has(a));

  // ── Worker session (neo / hawk involved) ─────────────────────────────────
  // Route into the active ordis activity thread (already on the ordis response
  // message) rather than creating a separate spin-up message. This keeps worker
  // activity contextual and respects Discord's one-thread-per-message limit.
  // The thread is renamed on first worker message to reflect the task/worker.
  // The user can reply in the thread — replies route back to the BeadHub session.
  if (involvesWorker) {
    if (!ordisChannel) {
      console.warn(
        "[bridge] Worker chat event received but ordis channel not configured — dropping",
      );
      return;
    }

    // Use the body included in the event payload (available since beadhub-a3g).
    // Fall back to an API fetch with backoff using the control-plane API key.
    let fromAlias: string | null = event.from_alias || null;
    let msgBody: string | null = event.body || null;

    if (msgBody === null) {
      const cpApiKey = config.controlPlane.apiKey || config.beadhub.apiKey;
      for (const delay of [0, 500, 1500, 3000, 5000]) {
        if (delay > 0) await new Promise((r) => setTimeout(r, delay));
        try {
          const msgs = cpApiKey
            ? await getSessionMessagesWithKey(event.session_id, cpApiKey, 200)
            : await getSessionMessages(event.session_id, 200, event.project_id || undefined);
          const target = msgs.find((m) => m.message_id === event.message_id);
          if (target) {
            fromAlias = target.from_agent;
            msgBody = target.body;
            break;
          }
        } catch (err) {
          console.warn(`[bridge] Error fetching worker message body: ${err}`);
        }
      }
    }

    if (fromAlias === null) {
      console.warn(
        `[bridge] Could not determine sender for worker message ${event.message_id} — skipping`,
      );
      return;
    }

    if (msgBody === null) {
      console.warn(
        `[bridge] Could not fetch body for worker message ${event.message_id} — skipping`,
      );
      return;
    }

    const thread = await getOrReuseOrdisThread(event, msgBody, ordisChannel, sessionMap, cmdRedis);
    if (!thread) return;

    await sendAsAgent(webhook, thread, fromAlias, msgBody);
    console.log(
      `[bridge] ${fromAlias} → ordis activity thread "${thread.name}": ${msgBody.slice(0, 80)}`,
    );

    await maybeRouteToOrchestrator(event, fromAlias, msgBody, thread, cmdRedis);
    return;
  }

  // ── Control-plane messages (ordis ↔ human/bridge, no workers) ────────────
  // Post flat to #ordis channel (no threads).
  if (
    ordisWebhookConfig &&
    event.project_id === ordisWebhookConfig.controlPlaneProjectId
  ) {
    // Use the body included in the event payload (available since beadhub-a3g).
    // Fall back to API fetch with backoff for older server versions that omit it.
    let msgBody: string | null = event.body || null;

    if (msgBody === null) {
      for (const delay of [0, 500, 1500, 3000, 5000]) {
        if (delay > 0) await new Promise((r) => setTimeout(r, delay));
        try {
          const msgs = await getSessionMessages(event.session_id, 2000, ordisWebhookConfig.controlPlaneProjectId);
          const target = msgs.find((m) => m.message_id === event.message_id);
          if (target) {
            msgBody = target.body;
            break;
          }
        } catch (err) {
          console.warn(`[bridge] Error fetching control-plane message: ${err}`);
        }
      }
    }

    if (msgBody === null) {
      console.warn(
        `[bridge] Could not fetch full body for message ${event.message_id} after all retries — skipping post to avoid truncation`,
      );
      return;
    }

    await postToOrdisChannel(event.from_alias, msgBody, cmdRedis, event.session_id);
    return;
  }

  // ── Unhandled: non-worker, non-control-plane messages ────────────────────
  // These are unexpected in the current 3-agent setup (ordis / neo / hawk).
  // Log and drop — #agent-comms routing has been intentionally removed.
  console.warn(
    `[bridge] Unhandled chat event from ${event.from_alias} (project ${event.project_id}) — no routing rule matched, dropping`,
  );
}

/** Agent alias → emoji prefix for ordis channel posts */
const AGENT_EMOJIS: Record<string, string> = {
  ordis: "🎯",
  neo: "🔧",
  hawk: "🦅",
};

/**
 * Route a worker chat message into the active ordis activity thread.
 *
 * Looks up `ordis:active_thread` in Redis (set by discord-listener when the
 * ordis activity thread is created for the current user request). On the first
 * worker message for this BeadHub session, renames the thread to reflect the
 * worker and task (e.g. "neo — hq-beadhub-295"), then maps the worker session
 * to the thread so the user can reply there and have it routed back to the
 * BeadHub chat session.
 */
async function getOrReuseOrdisThread(
  event: ChatMessageEvent,
  body: string,
  ordisChannel: TextChannel,
  sessionMap: SessionMap,
  redis: Redis,
): Promise<ThreadChannel | null> {
  // If this worker session already has a thread mapped, reuse it — but verify
  // the thread is still accessible (not deleted). If it's gone, clear the stale
  // mapping and fall through to find the current active thread.
  const existingThreadId = await sessionMap.getThreadId(event.session_id);
  if (existingThreadId) {
    try {
      const thread = await ordisChannel.threads.fetch(existingThreadId);
      if (thread && !thread.archived) return thread;
      if (thread?.archived) await thread.setArchived(false).catch(() => null);
      if (thread && !thread.archived) return thread;
    } catch {
      // Thread deleted or inaccessible — clear stale mapping and fall through
      console.warn(`[bridge] Stale thread mapping ${existingThreadId} for session ${event.session_id.slice(0, 8)} — clearing`);
    }
    // Clear stale session → thread mapping from Redis
    await redis.pipeline()
      .hdel("discord-bridge:sessions", event.session_id)
      .hdel("discord-bridge:threads", existingThreadId)
      .hdel("discord-bridge:session-source", existingThreadId)
      .exec();
  }

  // Look up the active ordis activity thread for this user request
  const activeThreadId = await redis.get("ordis:active_thread");
  if (!activeThreadId) {
    console.warn("[bridge] No active ordis thread found for worker message — dropping");
    return null;
  }

  let thread: ThreadChannel | null = null;
  try {
    thread = await ordisChannel.threads.fetch(activeThreadId);
  } catch {
    console.warn(`[bridge] Could not fetch active ordis thread ${activeThreadId} — dropping`);
    return null;
  }
  if (!thread) return null;
  if (thread.archived) await thread.setArchived(false);

  // Rename the thread to reflect the worker and task on first use
  const workerAlias =
    [event.from_alias, ...event.to_aliases].find((a) => WORKER_AGENTS.has(a)) ?? "worker";
  const beadId = extractBeadId(body);
  const threadName = (beadId ? `${workerAlias} — ${beadId}` : `${workerAlias} — activity`).slice(0, 100);
  if (thread.name !== threadName) {
    try {
      await thread.setName(threadName);
    } catch (err) {
      console.warn(`[bridge] Could not rename thread: ${err}`);
    }
  }

  // Map worker session → thread so subsequent messages and user replies route here
  await sessionMap.setWithSource(event.session_id, thread.id, "beadhub");

  console.log(
    `[bridge] Worker session ${event.session_id.slice(0, 8)}... mapped to ordis thread "${threadName}"`,
  );
  return thread;
}

/**
 * Deliver an ordis response to the #ordis Discord channel.
 *
 * When a placeholder message exists for the session (created when the user sent
 * their message), this EDITS that placeholder with the response text plus a
 * <@userId> mention so Discord notifies the user even through an edit.
 * Overflow chunks beyond the first are posted as new messages.
 *
 * Falls back to posting a new message when no placeholder is found.
 */
async function postToOrdisChannel(
  fromAlias: string,
  body: string,
  redis: Redis,
  sessionId: string,
): Promise<void> {
  if (!ordisWebhookConfig) return;

  const placeholderMsgId = await redis.get(`ordis:placeholder:${sessionId}`);
  const userId = await redis.get(`ordis:user:${sessionId}`);
  const mention = userId ? `\n<@${userId}>` : "";

  if (placeholderMsgId) {
    // --- Placeholder edit path ---
    // Reserve enough room for the mention on the last chunk.
    const maxBodyLen = config.maxDiscordMessageLength - mention.length;
    const bodyChunks = body.trim() ? splitMessage(body, maxBodyLen) : [];

    // Build the content for the placeholder edit (first or only chunk + mention).
    let editContent: string;
    if (bodyChunks.length === 0) {
      // Attachment-only or empty response — just the mention (or a fallback).
      editContent = mention.trimStart() || "✅";
    } else if (bodyChunks.length === 1) {
      editContent = bodyChunks[0] + mention;
    } else {
      editContent = bodyChunks[0];
    }

    await fetch(`${ordisWebhookConfig.webhookUrl}/messages/${placeholderMsgId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: editContent }),
    });

    // Post any overflow chunks as new messages (mention on the last one).
    if (bodyChunks.length > 1) {
      const emoji = AGENT_EMOJIS[fromAlias] ?? "🤖";
      const username = `${emoji} ${fromAlias}`;
      for (let i = 1; i < bodyChunks.length; i++) {
        const isLast = i === bodyChunks.length - 1;
        const content = isLast ? bodyChunks[i] + mention : bodyChunks[i];
        await fetch(ordisWebhookConfig.webhookUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, content }),
        });
      }
    }

    // Remove the placeholder and user keys — they've been consumed.
    await redis.del(`ordis:placeholder:${sessionId}`, `ordis:user:${sessionId}`);
  } else {
    // --- Fallback: post as a new message (no placeholder found) ---
    const emoji = AGENT_EMOJIS[fromAlias] ?? "🤖";
    const username = `${emoji} ${fromAlias}`;
    const chunks = splitMessage(body, config.maxDiscordMessageLength);
    for (const chunk of chunks) {
      await fetch(ordisWebhookConfig.webhookUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, content: chunk }),
      });
    }
  }

  // Stop typing indicator on the ordis channel.
  if (config.discord.ordisChannelId) {
    stopTypingIndicator(config.discord.ordisChannelId);
  }

  console.log(`[bridge->ordis] ${fromAlias}: ${body.slice(0, 80)}`);
}

function splitMessage(text: string, maxLen: number): string[] {
  if (text.length <= maxLen) return [text];
  const chunks: string[] = [];
  let remaining = text;
  while (remaining.length > 0) {
    if (remaining.length <= maxLen) {
      chunks.push(remaining);
      break;
    }
    let splitAt = remaining.lastIndexOf("\n", maxLen);
    if (splitAt <= 0) splitAt = maxLen;
    chunks.push(remaining.slice(0, splitAt));
    remaining = remaining.slice(splitAt).replace(/^\n/, "");
  }
  return chunks;
}

/**
 * If the chat message targets the orchestrator, push it to `orchestrator:inbox`
 * so the dispatcher can wake up and handle it via `processChatMessage()`.
 */
async function maybeRouteToOrchestrator(
  event: ChatMessageEvent,
  fromAlias: string,
  body: string,
  thread: ThreadChannel,
  cmdRedis: Redis,
): Promise<void> {
  const orchestratorAlias = config.orchestrator.alias;

  // Don't relay the orchestrator's own responses back to itself
  if (fromAlias === orchestratorAlias) return;

  // Only route if the orchestrator is one of the recipients
  if (!event.to_aliases.includes(orchestratorAlias)) return;

  // Look up repo origin for the project
  let repoOrigin = "";
  try {
    const repos = await getProjectRepos(event.project_id);
    if (repos.length > 0) {
      repoOrigin = repos[0].canonical_origin;
    }
  } catch (err) {
    console.warn(`[bridge] Failed to fetch repos for project ${event.project_id}:`, err);
  }

  const inboxMessage = {
    type: "bdh_chat",
    thread_id: thread.id,
    from_alias: fromAlias,
    message: body,
    project_slug: event.project_slug ?? "",
    project_id: event.project_id,
    repo_origin: repoOrigin,
    chat_session_id: event.session_id,
    timestamp: event.timestamp,
  };

  await cmdRedis.rpush("orchestrator:inbox", JSON.stringify(inboxMessage));
  console.log(
    `[bridge] Routed bdh chat from ${fromAlias} to orchestrator:inbox (project: ${event.project_slug})`,
  );
}
