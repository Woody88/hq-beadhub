import { config, WORKER_CONFIG } from "./config.js";
import type { WorkerAlias } from "./config.js";
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

/**
 * Build the task prompt for a worker agent responding to a BeadHub chat message.
 */
function buildWorkerTask(
  alias: WorkerAlias,
  sessionId: string,
  fromAlias: string,
  allParticipants: string[],
  body: string,
): string {
  const { role } = WORKER_CONFIG[alias];
  const others = allParticipants.filter((p) => p !== alias).join(", ");
  const replyTarget = allParticipants.filter((p) => p !== alias).join(",");
  return (
    `You are ${alias}, a ${role} agent in the BeadHub multi-agent system. ` +
    `You are in a group chat session (session_id: ${sessionId}) with: ${others}. ` +
    `${fromAlias} just sent this message:\n\n` +
    `"${body}"\n\n` +
    `Read /home/node/work/CLAUDE.md for your full instructions. ` +
    `Respond using: bdh :aweb chat send-and-leave "${replyTarget}" "your response". ` +
    `Then exit.`
  );
}

/**
 * Spawn a one-shot K8s Job for a worker agent (neo or hawk) to handle a BeadHub chat message.
 * The Job runs claude, sends a reply via bdh, and exits — no idle polling.
 */
export async function spawnWorkerJob(
  alias: WorkerAlias,
  sessionId: string,
  fromAlias: string,
  allParticipants: string[],
  body: string,
  messageId: string,
): Promise<void> {
  const { role, repo } = WORKER_CONFIG[alias];
  const jobName = `${alias}-${messageId.slice(0, 8)}`;
  const task = buildWorkerTask(alias, sessionId, fromAlias, allParticipants, body);
  const escapedTask = task.replace(/'/g, "'\\''");

  const manifest = `apiVersion: batch/v1
kind: Job
metadata:
  name: ${jobName}
  namespace: ${config.job.namespace}
  labels:
    app: agent-worker
    alias: ${alias}
    managed-by: ai-dispatcher
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 300
  template:
    spec:
      serviceAccountName: orchestrator
      restartPolicy: Never
      containers:
        - name: worker
          image: ${config.job.workerImage}
          imagePullPolicy: Always
          env:
            - name: CLAUDE_CODE_USE_BEDROCK
              value: "0"
            - name: CLAUDE_CODE_OAUTH_TOKEN
              valueFrom:
                secretKeyRef:
                  name: claude-setup-token
                  key: token
            - name: GH_TOKEN
              valueFrom:
                secretKeyRef:
                  name: gh-pat
                  key: token
          command: ["bash", "-c"]
          args:
            - |
              set -e
              export PATH="/home/node/.local/bin:$PATH"
              gh auth setup-git
              mkdir -p /home/node/.claude
              cat > /home/node/.claude/settings.json << 'S'
              {"env":{"DISABLE_AUTOUPDATER":"1"},"skipDangerousModePermissionPrompt":true}
              S
              cat > /home/node/.claude.json << 'S'
              {"hasCompletedOnboarding":true,"hasTrustDialogAccepted":true,"hasTrustDialogHooksAccepted":true,"projects":{"/home/node/work":{"allowedTools":[],"hasTrustDialogAccepted":true}}}
              S
              gh repo clone ${repo} /home/node/work
              cd /home/node/work
              git config user.email "${alias}@nessei.com"
              git config user.name "${alias}"
              yes 2>/dev/null | bdh :init --beadhub-url ${config.beadhub.url} --project control-plane --role ${role} --alias ${alias} || true
              claude -p '${escapedTask}' --dangerously-skip-permissions
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "3"
              memory: 3Gi
`;

  const proc = Bun.spawn(["kubectl", "apply", "-f", "-", "-n", config.job.namespace], {
    stdin: new Blob([manifest]),
    stdout: "pipe",
    stderr: "pipe",
  });

  const exitCode = await proc.exited;
  if (exitCode !== 0) {
    const stderr = await new Response(proc.stderr).text();
    throw new Error(`Failed to spawn worker job ${jobName}: ${stderr}`);
  }

  console.log(`[job-manager] Spawned worker job ${jobName} for ${alias} (session ${sessionId.slice(0, 8)}...)`);
}
