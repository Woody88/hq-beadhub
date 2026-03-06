import type Redis from "ioredis";
import type { BeadHubEvent, ChatMessageEvent } from "./types.js";
import { WORKER_ALIASES, KEYS } from "./config.js";
import type { WorkerAlias } from "./config.js";
import { spawnWorkerJob } from "./job-manager.js";

const ORDIS_ALIAS = "ordis";

/** Dedup set: message_ids we've already dispatched. */
const dispatched = new Set<string>();

function isWorkerAlias(alias: string): alias is WorkerAlias {
  return (WORKER_ALIASES as readonly string[]).includes(alias);
}

/**
 * Forward a BeadHub chat event to the orchestrator inbox so ordis is
 * triggered event-driven rather than waiting for its next poll interval.
 * The orchestrator's existing poll loop handles the reply and routes it
 * back into the correct BeadHub session.
 */
async function notifyOrchestrator(redis: Redis, chat: ChatMessageEvent): Promise<void> {
  const payload = JSON.stringify({
    session_id: chat.session_id,
    from_alias: chat.from_alias,
    message: chat.body,
    participants: chat.to_aliases,
    timestamp: chat.created_at,
  });
  await redis.rpush(KEYS.ORCHESTRATOR_INBOX, payload);
  await redis.publish(KEYS.ORCHESTRATOR_NOTIFY, "1");
  console.log(
    `[beadhub-sub] Notified orchestrator of message from ${chat.from_alias} (session ${chat.session_id.slice(0, 8)}...)`,
  );
}

/**
 * Subscribe to BeadHub's events:* Redis pub/sub channel.
 * - Messages directed at neo or hawk → spawn a one-shot K8s Job
 * - Messages directed at ordis (in a group session) → push to orchestrator inbox
 *
 * Workers include relevance instructions so they only reply if the message
 * is addressed to them — hawk stays silent if the message is clearly for neo.
 */
export async function startBeadHubSubscriber(redis: Redis): Promise<void> {
  const sub = redis.duplicate();
  sub.on("error", (err) => console.error("[beadhub-sub] Redis error:", err.message));

  await sub.psubscribe("events:*");
  console.log("[beadhub-sub] PSUBSCRIBE events:* — listening for worker and ordis chat events");

  sub.on("pmessage", async (_pattern: string, _channel: string, raw: string) => {
    try {
      const event: BeadHubEvent = JSON.parse(raw);
      if (event.type !== "chat.message_sent") return;

      const chat = event as ChatMessageEvent;

      // Skip the bilateral discord-bridge ↔ ordis session — ordis's poll loop
      // already handles that via orchestrator:inbox populated by discord-bridge.
      // Only handle group sessions (where discord-bridge is NOT a participant).
      const isDiscordBridgeSession = chat.to_aliases.includes("discord-bridge");
      if (isDiscordBridgeSession) return;

      // For each target, skip if the sender IS that target (avoid self-reply loops)
      const targetWorkers = chat.to_aliases
        .filter(isWorkerAlias)
        .filter((alias) => alias !== chat.from_alias);
      const targetOrdis =
        chat.to_aliases.includes(ORDIS_ALIAS) && chat.from_alias !== ORDIS_ALIAS;

      if (targetWorkers.length === 0 && !targetOrdis) return;

      // Dedup: BeadHub fires the event for each participant — only dispatch once per message
      if (dispatched.has(chat.message_id)) return;
      dispatched.add(chat.message_id);
      setTimeout(() => dispatched.delete(chat.message_id), 60_000);

      const targets = [...targetWorkers, ...(targetOrdis ? [ORDIS_ALIAS] : [])];
      console.log(
        `[beadhub-sub] Message for [${targets.join(", ")}] from ${chat.from_alias} (session ${chat.session_id.slice(0, 8)}...)`,
      );

      await Promise.all([
        // Spawn one-shot Jobs for neo/hawk
        ...targetWorkers.map((alias) =>
          spawnWorkerJob(
            alias,
            chat.session_id,
            chat.from_alias,
            chat.to_aliases,
            chat.body,
            chat.message_id,
          ),
        ),
        // Notify ordis via orchestrator inbox if it's a recipient
        ...(targetOrdis ? [notifyOrchestrator(redis, chat)] : []),
      ]);
    } catch (err) {
      console.error("[beadhub-sub] Error handling event:", err);
    }
  });
}
