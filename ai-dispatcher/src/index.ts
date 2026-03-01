import Redis from "ioredis";
import { config } from "./config.js";
import { startConsumer } from "./redis-consumer.js";
import { startIdleMonitor, stopIdleMonitor } from "./idle-monitor.js";

async function main(): Promise<void> {
  console.log("[dispatcher] Starting AI Dispatcher...");

  // 1. Connect to Redis
  const redis = new Redis(config.redis.url);
  redis.on("error", (err) => console.error("[redis] Connection error:", err.message));
  await redis.ping();
  console.log("[redis] Connected");

  // 2. Start the main consumer loop (BLPOP ai:inbox)
  await startConsumer(redis);

  // 3. Start idle monitor (deletes Job after 1hr no messages)
  startIdleMonitor();

  // 4. Health check server
  const healthServer = Bun.serve({
    port: config.health.port,
    fetch(req) {
      const url = new URL(req.url);
      if (url.pathname === "/healthz") {
        const healthy = redis.status === "ready";
        return new Response(
          JSON.stringify({ ok: healthy, redis: redis.status }),
          {
            status: healthy ? 200 : 503,
            headers: { "Content-Type": "application/json" },
          },
        );
      }
      return new Response("Not Found", { status: 404 });
    },
  });

  console.log(`[health] Listening on :${healthServer.port}/healthz`);
  console.log("[dispatcher] Ready — waiting for messages on ai:inbox");

  // Graceful shutdown
  const shutdown = async () => {
    console.log("[dispatcher] Shutting down...");
    stopIdleMonitor();
    healthServer.stop();
    redis.disconnect();
    process.exit(0);
  };

  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  console.error("[dispatcher] Fatal error:", err);
  process.exit(1);
});
