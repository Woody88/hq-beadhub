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

  // Stop typing indicator — response has arrived
  stopTypingIndicator(thread_id);

  // Check if this thread belongs to an ordis session.
  // If so, edit the placeholder in the main #ordis channel and send attachments
  // as a follow-up there rather than posting inside the activity thread.
  const ordisSessionId = await redis.get(`ordis:thread_to_session:${thread_id}`);
  if (ordisSessionId && config.discord.ordisChannelId && config.discord.ordisWebhookUrl) {
    await handleOrdisOutboxMessage(
      ordisSessionId,
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

/**
 * Handle a final ordis response that arrived via the agent outbox.
 * Edits the placeholder message in the main #ordis channel with the response
 * text and a <@userId> mention, then sends any file attachments as a follow-up
 * message since Discord's edit API cannot add attachments.
 *
 * Attachment-only responses (empty text) produce a placeholder edit with just
 * the mention, followed by a separate message containing the files.
 */
async function handleOrdisOutboxMessage(
  sessionId: string,
  response: string,
  attachments: AgentAttachment[] | undefined,
  redis: Redis,
  client: Client,
): Promise<void> {
  const placeholderMsgId = await redis.get(`ordis:placeholder:${sessionId}`);
  const userId = await redis.get(`ordis:user:${sessionId}`);
  const mention = userId ? `\n<@${userId}>` : "";

  if (placeholderMsgId && config.discord.ordisWebhookUrl) {
    // Build edit content: response text + mention, or just the mention for attachment-only.
    const editContent = response.trim()
      ? response + mention
      : mention.trimStart() || "✅";

    await fetch(`${config.discord.ordisWebhookUrl}/messages/${placeholderMsgId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: editContent }),
    });

    await redis.del(`ordis:placeholder:${sessionId}`);
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
