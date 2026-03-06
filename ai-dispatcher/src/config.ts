export const WORKER_ALIASES = ["neo", "hawk"] as const;
export type WorkerAlias = (typeof WORKER_ALIASES)[number];

export const WORKER_CONFIG: Record<WorkerAlias, { role: string; repo: string }> = {
  neo: { role: "developer", repo: "Woody88/hq-beadhub" },
  hawk: { role: "reviewer", repo: "Woody88/hq-beadhub" },
};

export const config = {
  redis: {
    url: env("REDIS_URL", "redis://localhost:16379/0"),
  },
  beadhub: {
    url: env("BEADHUB_URL", "http://beadhub-api"),
  },
  job: {
    namespace: env("JOB_NAMESPACE", "beadhub"),
    name: env("JOB_NAME", "ai-job"),
    image: env("JOB_IMAGE", "ghcr.io/woody88/claude-agent:latest"),
    workerImage: env("WORKER_IMAGE", "ghcr.io/woody88/claude-agent:sha-9e2e8b5"),
    templatePath: env("JOB_TEMPLATE_PATH", "/etc/ai-dispatcher/job-template.yaml"),
  },
  idle: {
    timeoutMs: parseInt(env("IDLE_TIMEOUT_MS", String(60 * 60 * 1000)), 10), // 1 hour
    checkIntervalMs: parseInt(env("IDLE_CHECK_INTERVAL_MS", String(60 * 1000)), 10), // 60s
  },
  health: {
    port: parseInt(env("HEALTH_PORT", "3002"), 10),
  },
} as const;

/** Redis keys */
export const KEYS = {
  AI_INBOX: "ai:inbox",
  AI_JOB_INBOX: "ai-job:inbox",
  AI_OUTBOX: "ai:outbox",
} as const;

function env(key: string, fallback: string): string {
  return process.env[key] ?? fallback;
}
