import { config } from "./config.js";
import { readFileSync } from "fs";

let jobTemplateCache: string | null = null;

function getJobTemplate(): string {
  if (!jobTemplateCache) {
    jobTemplateCache = readFileSync(config.job.templatePath, "utf-8");
  }
  return jobTemplateCache;
}

/**
 * Check if the AI Job currently exists in K8s.
 */
export async function jobExists(): Promise<boolean> {
  const proc = Bun.spawn(
    ["kubectl", "get", "job", config.job.name, "-n", config.job.namespace, "--no-headers"],
    { stdout: "pipe", stderr: "pipe" },
  );
  await proc.exited;
  return proc.exitCode === 0;
}

/**
 * Create the AI Job from the ConfigMap-mounted template.
 */
export async function createJob(): Promise<void> {
  const template = getJobTemplate();
  const proc = Bun.spawn(["kubectl", "apply", "-f", "-", "-n", config.job.namespace], {
    stdin: new Blob([template]),
    stdout: "pipe",
    stderr: "pipe",
  });

  const exitCode = await proc.exited;
  if (exitCode !== 0) {
    const stderr = await new Response(proc.stderr).text();
    throw new Error(`Failed to create job: ${stderr}`);
  }

  console.log(`[job-manager] Created job ${config.job.name}`);
}

/**
 * Delete the AI Job (and its pod) to free resources.
 */
export async function deleteJob(): Promise<void> {
  const proc = Bun.spawn(
    [
      "kubectl",
      "delete",
      "job",
      config.job.name,
      "-n",
      config.job.namespace,
      "--ignore-not-found",
    ],
    { stdout: "pipe", stderr: "pipe" },
  );

  const exitCode = await proc.exited;
  if (exitCode !== 0) {
    const stderr = await new Response(proc.stderr).text();
    console.error(`[job-manager] Failed to delete job: ${stderr}`);
    return;
  }

  console.log(`[job-manager] Deleted job ${config.job.name}`);
}

/**
 * Ensure the Job exists, creating it if needed.
 * Returns true if the Job was just created.
 */
export async function ensureJob(): Promise<boolean> {
  if (await jobExists()) {
    return false;
  }
  await createJob();
  return true;
}
