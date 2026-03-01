import type Redis from "ioredis";
import { config, KEYS } from "./config.js";
import { ensureJob } from "./job-manager.js";
import { recordActivity } from "./idle-monitor.js";
import { threadIdToSessionUuid } from "./session.js";
import type { AiInboxMessage, AiJobInboxMessage } from "./types.js";

/**
 * Start the main consumer loop. BLPOP from ai:inbox, ensure the Job exists,
 * then forward the message (with session UUID) to ai-job:inbox.
 */
export async function startConsumer(redis: Redis): Promise<void> {
  // Dedicated connection for blocking BLPOP
  const blpopRedis = redis.duplicate();
  blpopRedis.on("error", (err) => {
    console.error("[consumer] Redis error:", err.message);
  });

  console.log("[consumer] Starting BLPOP loop on", KEYS.AI_INBOX);

  // Run in background — don't block startup
  (async () => {
    while (true) {
      try {
        const result = await blpopRedis.blpop(KEYS.AI_INBOX, 0);
        if (!result) continue;

        const [, raw] = result;
        await handleInboxMessage(redis, raw);
      } catch (err) {
        console.error("[consumer] BLPOP error:", err);
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  })();
}

async function handleInboxMessage(redis: Redis, raw: string): Promise<void> {
  let msg: AiInboxMessage;
  try {
    msg = JSON.parse(raw);
  } catch (err) {
    console.error("[consumer] Invalid JSON:", raw.slice(0, 200));
    return;
  }

  const { thread_id, author, message, timestamp } = msg;
  console.log(`[consumer] ${author} in thread ${thread_id}: ${message.slice(0, 80)}`);

  // Record activity to reset idle timer
  recordActivity();

  // Ensure Job exists (creates if needed)
  const created = await ensureJob();
  if (created) {
    console.log("[consumer] Job was just created, waiting for it to be ready...");
    // Give the Job pod a moment to start and begin its BLPOP
    await new Promise((r) => setTimeout(r, 5000));
  }

  // Compute deterministic session UUID from thread ID
  const sessionUuid = threadIdToSessionUuid(thread_id);

  // Forward to ai-job:inbox with session UUID
  const jobMsg: AiJobInboxMessage = {
    thread_id,
    message: `[${author}] ${message}`,
    session_uuid: sessionUuid,
    timestamp,
  };

  await redis.rpush(KEYS.AI_JOB_INBOX, JSON.stringify(jobMsg));
  console.log(
    `[consumer] Forwarded to ${KEYS.AI_JOB_INBOX} (session: ${sessionUuid.slice(0, 8)}...)`,
  );
}
