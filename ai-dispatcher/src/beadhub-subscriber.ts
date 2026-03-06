import type Redis from "ioredis";
import type { BeadHubEvent, ChatMessageEvent } from "./types.js";
import { WORKER_ALIASES } from "./config.js";
import type { WorkerAlias } from "./config.js";
import { spawnWorkerJob } from "./job-manager.js";

/** Dedup set: message_ids we've already dispatched. */
const dispatched = new Set<string>();

function isWorkerAlias(alias: string): alias is WorkerAlias {
  return (WORKER_ALIASES as readonly string[]).includes(alias);
}

/**
 * Subscribe to BeadHub's events:* Redis pub/sub channel.
 * When a chat.message_sent event arrives directed at neo or hawk,
 * spawn a one-shot K8s Job to handle it.
 */
export async function startBeadHubSubscriber(redis: Redis): Promise<void> {
  const sub = redis.duplicate();
  sub.on("error", (err) => console.error("[beadhub-sub] Redis error:", err.message));

  await sub.psubscribe("events:*");
  console.log("[beadhub-sub] PSUBSCRIBE events:* — listening for worker chat events");

  sub.on("pmessage", async (_pattern: string, _channel: string, raw: string) => {
    try {
      const event: BeadHubEvent = JSON.parse(raw);
      if (event.type !== "chat.message_sent") return;

      const chat = event as ChatMessageEvent;

      // Only handle messages directed at neo or hawk
      const targetAlias = chat.to_aliases.find(isWorkerAlias);
      if (!targetAlias) return;

      // Dedup: BeadHub fires the event for each participant
      if (dispatched.has(chat.message_id)) return;
      dispatched.add(chat.message_id);
      setTimeout(() => dispatched.delete(chat.message_id), 60_000);

      console.log(
        `[beadhub-sub] Message for ${targetAlias} from ${chat.from_alias} (session ${chat.session_id.slice(0, 8)}...)`,
      );

      await spawnWorkerJob(
        targetAlias,
        chat.session_id,
        chat.from_alias,
        chat.body,
        chat.message_id,
      );
    } catch (err) {
      console.error("[beadhub-sub] Error handling event:", err);
    }
  });
}
