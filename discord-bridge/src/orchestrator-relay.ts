import type Redis from "ioredis";
import { AttachmentBuilder, type WebhookClient, type TextChannel } from "discord.js";
import type { SessionMap } from "./session-map.js";
import type { OrchestratorOutboxMessage, OrchestratorAttachment } from "./types.js";
import { stopTypingIndicator } from "./discord-listener.js";
import { config } from "./config.js";

const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024; // 8MB

const ORCHESTRATOR_OUTBOX = "orchestrator:outbox";

/**
 * Consume orchestrator responses from Redis outbox and post to Discord threads.
 * Uses BLPOP on a dedicated Redis connection to avoid blocking other operations.
 */
export async function startOrchestratorRelay(
  redis: Redis,
  channel: TextChannel,
  webhook: WebhookClient,
  sessionMap: SessionMap,
): Promise<void> {
  // Dedicated connection for blocking BLPOP
  const blpopRedis = redis.duplicate();
  blpopRedis.on("error", (err) => {
    console.error("[orchestrator-relay] Redis error:", err.message);
  });

  console.log("[orchestrator-relay] Starting BLPOP loop on", ORCHESTRATOR_OUTBOX);

  // Run in background — don't block startup
  (async () => {
    while (true) {
      try {
        const result = await blpopRedis.blpop(ORCHESTRATOR_OUTBOX, 0);
        if (!result) continue;

        const [, raw] = result;
        await handleOutboxMessage(raw, channel, webhook, sessionMap);
      } catch (err) {
        console.error("[orchestrator-relay] BLPOP error:", err);
        // Brief pause before retrying on connection errors
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  })();
}

async function handleOutboxMessage(
  raw: string,
  channel: TextChannel,
  webhook: WebhookClient,
  sessionMap: SessionMap,
): Promise<void> {
  let msg: OrchestratorOutboxMessage;
  try {
    msg = JSON.parse(raw);
  } catch (err) {
    console.error("[orchestrator-relay] Invalid JSON:", raw.slice(0, 200));
    return;
  }

  const { thread_id, session_id, response, attachments } = msg;

  // Stop typing indicator — response has arrived
  stopTypingIndicator(thread_id);

  // Fetch the thread
  let thread;
  try {
    thread = await channel.threads.fetch(thread_id);
  } catch (err) {
    console.error(`[orchestrator-relay] Could not fetch thread ${thread_id}:`, err);
    return;
  }

  if (!thread) {
    console.error(`[orchestrator-relay] Thread ${thread_id} not found`);
    return;
  }

  // Unarchive if needed
  if (thread.archived) {
    await thread.setArchived(false);
  }

  // Build Discord attachment objects, filtering out oversized files
  const files = buildAttachments(attachments ?? []);

  // Split long messages and send via webhook
  const chunks = splitMessage(response, config.maxDiscordMessageLength);
  for (let i = 0; i < chunks.length; i++) {
    // Only attach files to the last chunk so they appear after text
    const isLast = i === chunks.length - 1;
    await webhook.send({
      content: chunks[i],
      username: "🎯 orchestrator",
      threadId: thread.id,
      ...(isLast && files.length > 0 ? { files } : {}),
    });
  }

  const attachmentCount = attachments?.length ?? 0;
  console.log(
    `[orchestrator->discord] Response (${response.length} chars, ${attachmentCount} attachments) → thread ${thread.name ?? thread_id}`,
  );
}

/**
 * Decode base64 attachments into Discord AttachmentBuilder objects.
 * Files exceeding MAX_ATTACHMENT_BYTES are skipped with a warning logged.
 */
function buildAttachments(attachments: OrchestratorAttachment[]): AttachmentBuilder[] {
  const files: AttachmentBuilder[] = [];
  for (const att of attachments) {
    const buf = Buffer.from(att.data, "base64");
    if (buf.byteLength > MAX_ATTACHMENT_BYTES) {
      console.warn(
        `[orchestrator-relay] Skipping attachment "${att.filename}": ${buf.byteLength} bytes exceeds 8MB limit`,
      );
      continue;
    }
    files.push(new AttachmentBuilder(buf, { name: att.filename }));
  }
  return files;
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
    // Try to split at last newline within limit
    let splitAt = remaining.lastIndexOf("\n", maxLen);
    if (splitAt <= 0) splitAt = maxLen;
    chunks.push(remaining.slice(0, splitAt));
    remaining = remaining.slice(splitAt).replace(/^\n/, "");
  }
  return chunks;
}
