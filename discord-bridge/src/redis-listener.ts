import type Redis from "ioredis";
import type { TextChannel, ThreadChannel, WebhookClient } from "discord.js";
import type { BeadHubEvent, ChatMessageEvent, MailSentEvent } from "./types.js";
import type { SessionMap } from "./session-map.js";
import { config } from "./config.js";
import { getSessionMessages, getProjectRepos } from "./beadhub-client.js";
import { sendAsAgent, getOrCreateThread } from "./discord-sender.js";
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

      if (event.type === "chat.message_sent") {
        const chatEvent = event as unknown as ChatMessageEvent;
        // Skip messages sent by the bridge itself (human Discord replies relayed to BeadHub)
        if (chatEvent.from_alias === bridgeAlias) return;
        await handleChatMessage(chatEvent, cmdRedis, channel, webhook, sessionMap, echoTtlMs, bridgeAlias);
        return;
      }

      if (event.type === "mail.sent") {
        const mailEvent = event as unknown as MailSentEvent;
        await handleMailEvent(mailEvent);
        return;
      }
    } catch (err) {
      console.error("[redis] Error handling event:", err);
    }
  });
}

async function handleChatMessage(
  event: ChatMessageEvent,
  cmdRedis: Redis,
  channel: TextChannel,
  webhook: WebhookClient,
  sessionMap: SessionMap,
  echoTtlMs: number,
  bridgeAlias: string,
): Promise<void> {
  // Dedup: same chat message fires on each participant's channel
  if (wasRelayed(event.message_id)) return;
  markRelayed(event.message_id, echoTtlMs);

  // Human sessions are identified by the presence of `ordis:user:{sessionId}` in Redis,
  // set by discord-listener when a human sends a message from Discord.
  // Agent sessions (neo/hawk starting a chat with ordis) never go through discord-listener
  // so the key is never set — correctly identified as agent-only.
  const isHumanSession =
    ordisWebhookConfig !== null &&
    (await cmdRedis.exists(`ordis:user:${event.session_id}`)) === 1;
  const involvesHuman =
    isHumanSession ||
    event.from_alias === bridgeAlias ||
    event.to_aliases.includes(bridgeAlias);

  // Fetch message body — use HMAC (project-scoped) for all sessions.
  let fromAlias: string | null = event.from_alias || null;
  let msgBody: string | null = event.body || null;

  if (msgBody === null) {
    const projectId = event.project_id || ordisWebhookConfig?.controlPlaneProjectId;
    for (const delay of [0, 500, 1500, 3000, 5000]) {
      if (delay > 0) await new Promise((r) => setTimeout(r, delay));
      try {
        const msgs = await getSessionMessages(event.session_id, 200, projectId);
        const target = msgs.find((m) => m.message_id === event.message_id);
        if (target) {
          fromAlias = target.from_agent;
          msgBody = target.body;
          break;
        }
      } catch (err) {
        console.warn(`[bridge] Error fetching message body: ${err}`);
      }
    }
  }

  if (msgBody === null) {
    console.warn(`[bridge] Could not fetch body for message ${event.message_id} after retries — skipping`);
    return;
  }

  // ── Human session → flat to #ordis ────────────────────────────────────────
  if (involvesHuman) {
    await postToOrdisChannel(fromAlias, msgBody, cmdRedis, event.session_id);
    return;
  }

  // ── Agent-only session → #agent-comms thread ──────────────────────────────
  // One persistent thread per BeadHub session (session_id ↔ thread_id via session-map).
  // Thread name: sorted participant aliases joined with ↔ (e.g. "neo ↔ ordis").
  // Human replies in the thread route back to the session via discord-listener.
  const participants = [event.from_alias, ...event.to_aliases];
  const thread = await getOrCreateThread(channel, sessionMap, event.session_id, participants);

  await sendAsAgent(webhook, thread, fromAlias, msgBody);
  console.log(`[bridge] ${fromAlias} → #agent-comms thread "${thread.name}": ${msgBody.slice(0, 80)}`);

  try {
    await maybeNotifyOrdisOfCompletion(event, fromAlias, msgBody, thread);
  } catch (err) {
    console.warn("[bridge] maybeNotifyOrdisOfCompletion failed (non-fatal):", err);
  }
  await maybeRouteToOrchestrator(event, fromAlias, msgBody, thread, cmdRedis);
}

/** Agent alias → emoji prefix for ordis channel posts */
const AGENT_EMOJIS: Record<string, string> = {
  ordis: "🎯",
  neo: "🔧",
  hawk: "🦅",
};

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

/**
 * Forward a BeadHub mail message addressed to ordis into #ordis so Woodson
 * can see it without waiting for ordis to be triggered.
 *
 * Only mails TO ordis are forwarded — agent-to-agent mail on other projects
 * stays in BeadHub and is not surfaced in Discord.
 */
async function handleMailEvent(event: MailSentEvent): Promise<void> {
  if (!ordisWebhookConfig) return;

  const orchestratorAlias = config.orchestrator.alias;
  if (event.to_alias !== orchestratorAlias) return;

  const emoji = AGENT_EMOJIS[event.from_alias] ?? "🤖";
  const username = `${emoji} ${event.from_alias}`;
  const subject = event.subject ? ` [${event.subject}]` : "";
  const content = `📬 **Mail to ordis**${subject}\n${event.body}`;

  const chunks = splitMessage(content, config.maxDiscordMessageLength);
  for (const chunk of chunks) {
    await fetch(ordisWebhookConfig.webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, content: chunk }),
    });
  }

  console.log(`[bridge->ordis] mail from ${event.from_alias}: ${event.body.slice(0, 80)}`);
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
 * Completion signal keywords — any message from a worker to ordis containing
 * one of these phrases is treated as a task completion notification.
 */
const COMPLETION_SIGNALS = ["pr #", "ready for review", "task complete", "task completed"];

function isCompletionSignal(body: string): boolean {
  const lower = body.toLowerCase();
  return COMPLETION_SIGNALS.some((signal) => lower.includes(signal));
}

/**
 * When a worker sends a completion signal to ordis via chat, post a proactive
 * notification to the #ordis channel with a link to the #agent-comms thread
 * so Woodson is immediately informed without waiting for ordis to reply.
 */
async function maybeNotifyOrdisOfCompletion(
  event: ChatMessageEvent,
  fromAlias: string,
  body: string,
  thread: ThreadChannel,
): Promise<void> {
  if (!ordisWebhookConfig) return;
  if (!isCompletionSignal(body)) return;

  const orchestratorAlias = config.orchestrator.alias;

  // Don't notify when the orchestrator is the sender (avoid self-notification)
  if (fromAlias === orchestratorAlias) return;

  // Only notify when the message is directed to the orchestrator
  if (!event.to_aliases.includes(orchestratorAlias)) return;

  const emoji = AGENT_EMOJIS[fromAlias] ?? "🤖";
  const username = `${emoji} ${fromAlias}`;
  const threadLink = `https://discord.com/channels/${thread.guildId}/${thread.id}`;
  const content = `📣 **${fromAlias}** sent a completion update → [#agent-comms thread](${threadLink})\n${body}`;

  const chunks = splitMessage(content, config.maxDiscordMessageLength);
  for (const chunk of chunks) {
    await fetch(ordisWebhookConfig.webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, content: chunk }),
    });
  }

  console.log(`[bridge->ordis] completion signal from ${fromAlias}: ${body.slice(0, 80)}`);
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
