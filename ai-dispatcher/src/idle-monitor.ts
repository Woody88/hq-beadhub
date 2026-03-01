import { config } from "./config.js";
import { deleteJob, jobExists } from "./job-manager.js";

let lastActivityMs = 0;
let monitorInterval: Timer | null = null;

/** Record activity — resets the idle timer. */
export function recordActivity(): void {
  lastActivityMs = Date.now();
}

/**
 * Start the idle monitor. Checks periodically if the Job has been idle
 * longer than the configured timeout, and deletes it if so.
 */
export function startIdleMonitor(): void {
  if (monitorInterval) return;

  console.log(
    `[idle-monitor] Started (timeout: ${config.idle.timeoutMs / 1000}s, check every ${config.idle.checkIntervalMs / 1000}s)`,
  );

  monitorInterval = setInterval(async () => {
    try {
      // No activity recorded yet — nothing to monitor
      if (lastActivityMs === 0) return;

      const idleMs = Date.now() - lastActivityMs;
      if (idleMs < config.idle.timeoutMs) return;

      // Check if job actually exists before trying to delete
      if (!(await jobExists())) return;

      console.log(
        `[idle-monitor] Job idle for ${Math.round(idleMs / 1000)}s — exceeds ${config.idle.timeoutMs / 1000}s timeout, deleting`,
      );

      await deleteJob();
      lastActivityMs = 0; // Reset so we don't keep trying to delete
    } catch (err) {
      console.error("[idle-monitor] Error:", err);
    }
  }, config.idle.checkIntervalMs);
}

/** Stop the idle monitor. */
export function stopIdleMonitor(): void {
  if (monitorInterval) {
    clearInterval(monitorInterval);
    monitorInterval = null;
  }
}
