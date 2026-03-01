import type Redis from "ioredis";
import type { WebhookClient, TextChannel } from "discord.js";
import type { AiOutboxMessage } from "./types.js";
import { stopTypingIndicator } from "./discord-listener.js";
import { config } from "./config.js";

const AI_OUTBOX = "ai:outbox";

/**
 * Consume AI Job responses from ai:outbox and post to Discord threads
 * in the AI channel. Uses BLPOP on a dedicated Redis connection.
 */
export async function startAiRelay(
  redis: Redis,
  channel: TextChannel,
  webhook: WebhookClient,
): Promise<void> {
  // Dedicated connection for blocking BLPOP
  const blpopRedis = redis.duplicate();
  blpopRedis.on("error", (err) => {
    console.error("[ai-relay] Redis error:", err.message);
  });

  console.log("[ai-relay] Starting BLPOP loop on", AI_OUTBOX);

  // Run in background — don't block startup
  (async () => {
    while (true) {
      try {
        const result = await blpopRedis.blpop(AI_OUTBOX, 0);
        if (!result) continue;

        const [, raw] = result;
        await handleOutboxMessage(raw, channel, webhook);
      } catch (err) {
        console.error("[ai-relay] BLPOP error:", err);
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  })();
}

async function handleOutboxMessage(
  raw: string,
  channel: TextChannel,
  webhook: WebhookClient,
): Promise<void> {
  let msg: AiOutboxMessage;
  try {
    msg = JSON.parse(raw);
  } catch (err) {
    console.error("[ai-relay] Invalid JSON:", raw.slice(0, 200));
    return;
  }

  const { thread_id, response } = msg;

  // Stop typing indicator
  stopTypingIndicator(thread_id);

  // Fetch the thread
  let thread;
  try {
    thread = await channel.threads.fetch(thread_id);
  } catch (err) {
    console.error(`[ai-relay] Could not fetch thread ${thread_id}:`, err);
    return;
  }

  if (!thread) {
    console.error(`[ai-relay] Thread ${thread_id} not found`);
    return;
  }

  // Unarchive if needed
  if (thread.archived) {
    await thread.setArchived(false);
  }

  // Split long messages and send via webhook
  const chunks = splitMessage(response, config.maxDiscordMessageLength);
  for (const chunk of chunks) {
    await webhook.send({
      content: chunk,
      username: "Claude",
      threadId: thread.id,
    });
  }

  console.log(
    `[ai->discord] Response (${response.length} chars) → thread ${thread.name ?? thread_id}`,
  );
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
