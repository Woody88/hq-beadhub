import type Redis from "ioredis";
import type { Client, WebhookClient, TextChannel } from "discord.js";
import type { OrchestratorOutboxMessage, AgentOutboxMessage, AgentAttachment } from "./types.js";
import { sendAsAgent, buildAttachments } from "./discord-sender.js";
import { stopTypingIndicator } from "./discord-listener.js";
import { config } from "./config.js";

const ORCHESTRATOR_OUTBOX = "orchestrator:outbox";
const AGENT_OUTBOX = "agent:outbox";

/**
 * Consume agent responses from Redis outbox queues and post to Discord threads.
 *
 * Listens on two queues via BLPOP:
 *   - orchestrator:outbox  — messages from the orchestrator Deployment (legacy format, no from_alias)
 *   - agent:outbox         — messages from any agent (AgentOutboxMessage, includes from_alias)
 *
 * Uses a dedicated Redis connection to avoid blocking other operations.
 */
export async function startOrchestratorRelay(
  redis: Redis,
  channel: TextChannel,
  webhook: WebhookClient,
  client: Client,
): Promise<void> {
  // Dedicated connection for blocking BLPOP
  const blpopRedis = redis.duplicate();
  blpopRedis.on("error", (err) => {
    console.error("[agent-relay] Redis error:", err.message);
  });

  // On startup: discard messages older than 5 minutes to prevent flooding Discord after a restart.
  const STALE_THRESHOLD_MS = 5 * 60 * 1000;
  for (const queue of [ORCHESTRATOR_OUTBOX, AGENT_OUTBOX]) {
    try {
      const items = await redis.lrange(queue, 0, -1);
      if (items.length === 0) continue;
      const cutoff = Date.now() - STALE_THRESHOLD_MS;
      let staleCount = 0;
      for (const item of items) {
        try {
          const parsed = JSON.parse(item) as { timestamp?: string };
          const ts = parsed.timestamp ? new Date(parsed.timestamp).getTime() : 0;
          if (ts < cutoff) {
            staleCount++;
          } else {
            break; // Queue is FIFO; first fresh message means the rest are also fresh
          }
        } catch {
          staleCount++; // Unparseable — treat as stale and discard
        }
      }
      if (staleCount > 0) {
        await redis.ltrim(queue, staleCount, -1);
        console.warn(
          `[agent-relay] Startup purge: discarded ${staleCount}/${items.length} stale messages from ${queue}`,
        );
      }
    } catch (err) {
      console.warn(`[agent-relay] Could not purge stale messages from ${queue}:`, err);
    }
  }

  console.log(
    `[agent-relay] Starting BLPOP loop on [${ORCHESTRATOR_OUTBOX}, ${AGENT_OUTBOX}]`,
  );

  // Run in background — don't block startup
  (async () => {
    while (true) {
      // Separate BLPOP errors (connection loss) from send errors so a transient Discord API
      // failure does not permanently stall the loop.
      let result: [string, string] | null;
      try {
        result = await blpopRedis.blpop(ORCHESTRATOR_OUTBOX, AGENT_OUTBOX, 0);
      } catch (err) {
        console.error("[agent-relay] BLPOP error:", err);
        // Brief pause before retrying on connection errors
        await new Promise((r) => setTimeout(r, 2000));
        continue;
      }

      if (!result) continue;

      const [key, raw] = result;
      try {
        await handleOutboxMessage(key, raw, channel, webhook, client, redis);
      } catch (err) {
        console.error(`[agent-relay] Failed to handle outbox message from ${key} — skipping:`, err);
      }
    }
  })();
}

async function handleOutboxMessage(
  key: string,
  raw: string,
  channel: TextChannel,
  webhook: WebhookClient,
  client: Client,
  redis: Redis,
): Promise<void> {
  let msg: OrchestratorOutboxMessage | AgentOutboxMessage;
  try {
    msg = JSON.parse(raw);
  } catch {
    console.error("[agent-relay] Invalid JSON:", raw.slice(0, 200));
    return;
  }

  // Determine from_alias: AgentOutboxMessage carries it; orchestrator:outbox implies "orchestrator"
  const fromAlias =
    key === AGENT_OUTBOX
      ? (msg as AgentOutboxMessage).from_alias
      : "orchestrator";

  if (!fromAlias) {
    console.error(`[agent-relay] Missing from_alias in message from ${key}`);
    return;
  }

  const { thread_id, response, attachments } = msg;

  // Check if this thread belongs to an ordis session.
  // If so, edit the placeholder in the main #ordis channel and send attachments
  // as a follow-up there rather than posting inside the activity thread.
  const ordisSessionId = await redis.get(`ordis:thread_to_session:${thread_id}`);
  if (ordisSessionId && config.discord.ordisChannelId && config.discord.ordisWebhookUrl) {
    // Typing indicator was started on the ordis channel, not the activity thread.
    stopTypingIndicator(config.discord.ordisChannelId);
    await handleOrdisOutboxMessage(
      ordisSessionId,
      fromAlias,
      response,
      attachments,
      redis,
      client,
    );
    const attachmentCount = attachments?.length ?? 0;
    console.log(
      `[${fromAlias}->ordis] Response (${response.length} chars, ${attachmentCount} attachments) via placeholder edit`,
    );
    return;
  }

  // Stop typing indicator — response has arrived
  stopTypingIndicator(thread_id);

  // Fetch the thread
  let thread;
  try {
    thread = await channel.threads.fetch(thread_id);
  } catch (err) {
    console.error(`[agent-relay] Could not fetch thread ${thread_id}:`, err);
    return;
  }

  if (!thread) {
    console.error(`[agent-relay] Thread ${thread_id} not found`);
    return;
  }

  // Unarchive if needed
  if (thread.archived) {
    await thread.setArchived(false);
  }

  await sendAsAgent(webhook, thread, fromAlias, response, attachments, client);

  const attachmentCount = attachments?.length ?? 0;
  console.log(
    `[${fromAlias}->discord] Response (${response.length} chars, ${attachmentCount} attachments) → thread ${thread.name ?? thread_id}`,
  );
}

/** Agent alias → emoji prefix for ordis channel posts */
const AGENT_EMOJIS: Record<string, string> = {
  ordis: "🎯",
  neo: "🔧",
  hawk: "🦅",
};

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
 * Handle a final ordis response that arrived via the agent outbox.
 * Edits the placeholder message in the main #ordis channel with the response
 * text and a <@userId> mention, then sends any file attachments as a follow-up
 * message since Discord's edit API cannot add attachments.
 *
 * Long responses are split into chunks: the placeholder is edited with the
 * first chunk, and overflow chunks are posted as new channel messages with the
 * mention appended to the last chunk only.
 *
 * Attachment-only responses (empty text) produce a placeholder edit with just
 * the mention, followed by a separate message containing the files.
 */
async function handleOrdisOutboxMessage(
  sessionId: string,
  fromAlias: string,
  response: string,
  attachments: AgentAttachment[] | undefined,
  redis: Redis,
  client: Client,
): Promise<void> {
  const placeholderMsgId = await redis.get(`ordis:placeholder:${sessionId}`);
  const userId = await redis.get(`ordis:user:${sessionId}`);
  const mention = userId ? `\n<@${userId}>` : "";

  if (placeholderMsgId && config.discord.ordisWebhookUrl) {
    // Reserve enough room for the mention on the last chunk.
    const maxBodyLen = config.maxDiscordMessageLength - mention.length;
    const bodyChunks = response.trim() ? splitMessage(response, maxBodyLen) : [];

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

    await fetch(`${config.discord.ordisWebhookUrl}/messages/${placeholderMsgId}`, {
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
        await fetch(config.discord.ordisWebhookUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, content }),
        });
      }
    }

    await redis.del(`ordis:placeholder:${sessionId}`, `ordis:user:${sessionId}`);
  }

  // Send attachments as a follow-up in the main ordis channel (Discord edit API
  // cannot include attachments, so they must be a separate message).
  if (attachments && attachments.length > 0 && config.discord.ordisChannelId) {
    const files = buildAttachments(attachments);
    if (files.length > 0) {
      const ordisChannel = await client.channels.fetch(config.discord.ordisChannelId);
      if (ordisChannel && ordisChannel.isTextBased() && !ordisChannel.isDMBased()) {
        await (ordisChannel as TextChannel).send({ files });
      }
    }
  }
}
