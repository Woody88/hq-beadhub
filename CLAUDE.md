# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Autonomous multi-agent development pipeline where AI agents handle the full software development lifecycle — planning, implementation, testing, and PR submission — with minimal human involvement. The human role is limited to initial plan approval and escalation resolution.

**Owner:** Woodson / Nessei Inc.
**Current Phase:** Phase 1 — Local Validation

## Architecture

Three-phase system built on open, self-hostable infrastructure:

### Coordination Layer
- **BeadHub** (self-hosted Python API + frontend) — central coordination server at `http://localhost:8000`
- **PostgreSQL** — persistent state (claims, issues, policies)
- **Redis** — ephemeral state (presence, locks, messages)
- All three run via Docker Compose locally (Phase 1), then k3s on Raspberry Pi 5 (Phase 2+)

### Agent Team (Fixed Aliases)

The following three agents are the **permanent team** across ALL BeadHub projects. These are the ONLY aliases that may be used.

| Alias | Role | Description |
|-------|------|-------------|
| **ordis** | coordinator | Global orchestrator (control-plane pod). Plans, assigns, reviews, unblocks. Reachable via Discord `#ordis` channel. |
| **neo** | developer | Worker agent. Implements features, fixes bugs, submits PRs. |
| **hawk** | reviewer | QA/review agent. Reviews PRs, checks security, test coverage, code quality. |

**Rules:**
- Agents must ONLY use these three aliases — no ad-hoc names (no worker-xyz, no task-dev, etc.)
- Same compute can serve all projects — agents switch context by pulling the repo and running `bdh :init --alias <name> --role <role>`
- ordis is the coordinator for every project; neo and hawk register per-project as needed
- If a project needs more agents, get human approval first

### Coordination Flow
1. Human gives feature spec to ordis (coordinator)
2. ordis breaks spec into Beads tickets via `bdh` CLI
3. Human approves plan
4. ordis delegates to neo (persistent Deployment) via `bdh :aweb chat send-and-leave neo "task..."` — neo picks it up within ~5s
5. Blockers resolved agent-to-agent via BeadHub chat; only true escalations surface to human
6. neo submits PR on completion
7. ordis delegates review to hawk via `bdh :aweb chat send-and-leave hawk "review PR #N"`

### Worker Communication Policy

**ordis MUST include these instructions in every task assignment to neo or hawk:**

- Use `bdh :aweb chat send-and-leave <alias> "msg"` for task delegation and status updates (non-blocking — does NOT block the caller's session).
- Use `bdh :aweb mail send ordis "msg"` ONLY for the final handoff (e.g., "PR #123 is open — summary of changes").
- Do NOT use `send-and-wait` for delegation — it blocks the caller's Claude session until a reply arrives.
- Do NOT use PR comments, commit messages, or issue updates as the primary communication channel with other agents.
- **Format ALL chat messages in Discord markdown** — use ` ```language\ncode\n``` ` for code blocks, `**bold**` for emphasis, and bullet lists for structured output. Do NOT use plain text or GitHub-style markdown (no `##` headings, no `> blockquotes`). Discord renders its own markdown subset; plain text and GitHub markdown render poorly in threads.

**Why:** neo and hawk are persistent Deployments that poll BeadHub chat every ~5s. Discord-bridge creates a thread in `#agent-comms` for every chat session involving a worker, and workers post real-time tool activity to those threads. Woodson can observe agent progress and intervene when needed. Mail is fire-and-forget and not surfaced in Discord; it is only appropriate for terminal notifications (handoffs).

### Key Tools
- **`bdh`** — Beads CLI (git-native issue tracking)
- **`bdh`** — BeadHub CLI (coordination, chat, locks, presence)
- **Ralph Loop** — persistent agent iteration pattern (max 30 iterations)

## Phase 1 Setup (Local Validation)

```bash
# Start BeadHub stack
make start                          # Docker Compose: beadhub + postgres + redis

# Initialize workspaces (fixed team)
bdh :init --alias ordis --role coordinator          # Register ordis (coordinator)
bdh :add-worktree developer --alias neo             # Register neo (developer)
bdh :add-worktree reviewer --alias hawk             # Register hawk (reviewer)
```

ordis, neo, and hawk run as separate Claude Code instances in separate git worktrees, coordinating through BeadHub.

## Phase 2+ Infrastructure

- **Daytona** — isolated compute sandboxes for workers (sub-90ms creation, pay-per-second)
- **Cloudflare Tunnel + Access** — zero-trust ingress to BeadHub on Pi 5
- **GitHub** — PR submission and code review
- **Discord** (Phase 3) — escalation notifications and PR alerts

## CRITICAL: Ticket Sync Rules — No Local Dolt

Agents must NEVER use a local dolt database for ticket operations. All ticket data flows through git and the BeadHub server.

**Allowed:**
- `bdh list`, `bdh show`, `bdh ready` — reads from BeadHub server API
- `bdh create`, `bdh update`, `bdh close` — writes to local git-backed JSONL
- `bdh sync` — pushes JSONL to git remote, pulls updates

**Forbidden:**
- Starting or depending on a local dolt database
- Attempting to fix dolt `table not found` errors — use `bdh` (server) instead
- Syncing tickets from the upstream fork (`beadhub/beadhub`)

**Ticket creation flow:**
1. `bdh create ...` (creates in local JSONL)
2. `bdh sync` (pushes to git remote via `beads-sync` branch)
3. BeadHub server picks up changes from git

**If `bdh` commands fail**, fall back to `bdh` (server API). Never try to repair a local database.

## CRITICAL: Agent Identity Rules

Agents must ONLY use aliases that are **pre-registered in the BeadHub server**. Never create ad-hoc or one-off aliases.

**Current registered team:**

| Alias | Role |
|-------|------|
| **ordis** | coordinator |
| **neo** | developer |
| **hawk** | reviewer |

**Rules for ALL agents (including any future additions):**
- Check registered aliases with `bdh :aweb who` before starting work
- ONLY use an alias that appears in the registered list — never invent new ones
- To add a new agent, get human approval first, then register via `bdh :add-worktree <role> --alias <name>`
- All agents are registered per-project in BeadHub via `bdh :init --alias <name> --role <role>`
- Same compute machine can work across projects — switch by pulling the repo and running `bdh :init`
- The coordinator receives all agent messages via the bdh notify hook
- Chat and mail are scoped per-project, so `bdh :init` into the correct repo before communicating

**Switching projects (applies to ALL agents):**
```bash
cd ~/workspace/<project-repo>
bdh :init --alias <your-alias> --role <your-role>
bdh :status    # verify identity
bdh ready      # start working
```

**Why this matters:** Ad-hoc aliases lose chat history, can't be coordinated, and create identity sprawl on the server. Pre-registered aliases ensure persistent memory and proper coordination.

## Key Design Decisions

- No vendor lock-in beyond Claude API — all infrastructure is self-hostable
- Agents coordinate without human relay; human is only in the loop for plan approval and escalations
- Ralph Loop has a hard cap (`--max-iterations 30`) to prevent cost runaway
- Workers use file locks via BeadHub to avoid conflicts
- Claude Code PostToolUse hook handles incoming chat while workers are in Ralph Loop

## Infrastructure Architecture

### Control-Plane Project (BeadHub)

ordis operates from a **central control-plane project** in BeadHub (`control-plane` slug). This project is project-agnostic — it serves as ordis's inbox and coordination hub across ALL projects. The architecture documentation is tracked in bead `beadhub-50q`.

**This repo (`hq-beadhub`) is ordis's central knowledge base.** All architecture decisions, beads/tickets, and coordination docs live here. ordis should always reference beads in this repo for context on the overall system.

- **Project slug:** `control-plane`
- **Project ID:** `57dc7ce5-4722-480e-a92c-a29b50ef41bb`
- **Discord channel:** `#ordis` (ID: `1478072914543775824`)

### Orchestrator Deployment (K8s)

ordis (the coordinator) runs as a **Deployment** in the `beadhub` namespace on a Raspberry Pi 5 (k3s). It uses a **message watcher** that detects pending BeadHub chat messages and processes them with `claude -p`.

```
Human ↔ Discord #ordis channel → discord-bridge → BeadHub chat (control-plane)
                                                          ↓
                                              message-watcher detects pending
                                                          ↓
                                              claude -p --resume processes message
                                                          ↓  (PostToolUse hooks)
                                                          ├── bdh :notify (catches new messages)
                                                          └── discord-status.sh (posts activity to Discord)
                                                          ↓
                                              response via bdh :aweb chat → bridge → Discord
```

**The ordis pod runs a message watcher + `claude -p`, NOT `claude remote-control`.** The entrypoint:
1. Sets up git auth, `bdh :init` for the control-plane project
2. Loops: checks `bdh :aweb chat pending` for incoming messages
3. When a message is pending, kicks `claude -p "Check pending messages" --resume <session>`
4. Claude processes the message, `bdh :notify` hook catches new messages mid-task
5. `discord-status.sh` hook posts real-time tool activity to Discord

**Authentication:**
- `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (1-year validity, no refresh needed)
- No credentials.json, no oauth-refresh sidecar, no init container

**Claude Code hooks** (settings.json):
- `bdh :notify` — PostToolUse hook, checks for new BeadHub chat messages after every tool use
- `discord-status.sh` — PostToolUse hook, posts tool activity to Discord (deterministic, 100% reliable)

### Worker Deployments (neo/hawk)

neo (developer) and hawk (reviewer) run as **persistent Deployments** in the `beadhub` namespace, polling BeadHub chat every ~5s. They use the same message-watcher pattern as ordis.

**How workers operate:**
1. Poll `$BEADHUB_API/v1/chat/pending` for actionable messages
2. Process messages with `claude -p --output-format stream-json --verbose`
3. Post real-time tool activity to `#agent-comms` Discord threads
4. Reply via BeadHub chat API (response routes through discord-bridge to Discord)

**Discord thread lookup:** Workers look up thread IDs from the `discord-bridge:sessions` Redis hash (set by `redis-listener.ts` / `session-map.ts`). This is different from ordis, which uses `ordis:thread:<session_id>` string keys (set by `discord-listener.ts` for `#ordis` channel).

**Thread posting:** Workers use the `#agent-comms` webhook (`DISCORD_WEBHOOK_URL`) with `?thread_id=` parameter. Usernames are `🔧 neo` and `🦅 hawk`.

**SKIP sentinel:** If Claude's response is just "SKIP" (or similar no-op), the response is suppressed and nothing is posted to BeadHub or Discord.

### CRITICAL: Do Not Modify the Orchestrator Deployment

**The orchestrator Deployment manifest is managed by ArgoCD from `Woody88/homelab-k8s`.** If an agent modifies it via `kubectl apply/patch/edit`, ArgoCD will revert the change and break the session.

**Rules:**
- The orchestrator Deployment is in `Woody88/homelab-k8s` at `manifests/platform/beadhub/orchestrator.yaml`
- Changes to the orchestrator entrypoint or CLAUDE.md must go through a commit to homelab-k8s (ArgoCD syncs from Git)
- Agents must NEVER `kubectl patch/apply/edit` the `orchestrator` Deployment directly
- Agents CAN create/modify Jobs (workers), ConfigMaps, and other resources freely
- If the orchestrator pod is not responding, check: `kubectl logs deployment/orchestrator -n beadhub`

### Related Repos

| Repo | Contains |
|------|----------|
| `Woody88/hq-beadhub` (this repo) | discord-bridge source, agent-image Dockerfile, beads, project docs |
| `Woody88/homelab-k8s` | K8s manifests including orchestrator Deployment, RBAC, kustomization |
| `beadhub/beadhub` | Upstream BeadHub (this repo was originally forked from here) |

### CRITICAL: Git Remote Rules

This repo is a fork of `beadhub/beadhub`, but **the `upstream` remote has been intentionally removed**. The only remote is `origin` → `Woody88/hq-beadhub`.

**Rules for ALL agents:**
- **NEVER add an `upstream` remote** pointing to `beadhub/beadhub`
- **NEVER push to `beadhub/beadhub`** — not fixes, not PRs, not anything
- **ALL pushes go to `origin` (`Woody88/hq-beadhub`) only**
- If you need upstream changes, the human will handle cherry-picks manually
- If `git remote -v` shows any remote other than `origin`, stop and ask the human

### Discord Bridge

Source: `discord-bridge/src/` in this repo. Published to `ghcr.io/woody88/discord-bridge:latest`.

Key files:
- `config.ts` — All env var configuration. Includes ordis channel (`DISCORD_ORDIS_CHANNEL_ID`, `DISCORD_ORDIS_WEBHOOK_URL`) and control-plane (`CONTROL_PLANE_API_KEY`, `CONTROL_PLANE_PROJECT_ID`)
- `discord-listener.ts` — Routes Discord messages. `#ordis` channel messages (flat, no threads) → BeadHub control-plane chat via `createOrSendChat()`. Thread messages → existing BeadHub sessions or orchestrator chat
- `redis-listener.ts` — Subscribes to Redis `events:*`. Control-plane project messages → posts to `#ordis` channel directly via webhook (flat, no threads). Other project messages → creates/uses Discord threads
- `beadhub-client.ts` — BeadHub API client. `createOrSendChat()` accepts optional `apiKeyOverride` for control-plane routing
- `session-map.ts` — Maps Discord thread IDs ↔ BeadHub session IDs with source tracking ("beadhub" | "orchestrator" | "ai")

**Routing summary:**
- `#ordis` channel → control-plane project (flat conversation, uses `CONTROL_PLANE_API_KEY` for a `discord-bridge` identity registered in the control-plane project)
- `#agent-comms` threads → hq-beadhub project (uses `BEADHUB_API_KEY`)
- `#ai` threads → ai:inbox Redis list (for AI dispatcher)
- Control-plane responses → `#ordis` channel via ordis webhook (no threads)
- Other project responses → `#agent-comms` threads

### Agent Image

Dockerfile: `agent-image/Dockerfile` in this repo. Published to `ghcr.io/woody88/claude-agent:latest`. Contains:
- Node.js 22, npm, Claude Code CLI, kubectl, gh, bd, bdh, dolt, wrangler

Scripts (in `agent-image/`, mounted via ConfigMap in K8s — not baked into image):
- `message-watcher.sh` — Orchestrator entrypoint: `bdh :init` → post online message → poll `bdh :aweb chat pending` → kick `claude -p --resume`
- `discord-status.sh` — PostToolUse hook: rate-limited (5s), posts tool activity to `#ordis` via webhook

<!-- BEADHUB:START -->
## BeadHub Coordination Rules

This project uses `bdh` for multi-agent coordination and issue tracking, `bdh` is a wrapper on top of `bd` (beads). Commands starting with : like `bdh :status` are managed by `bdh`. Other commands are sent to `bd`.

You are expected to work and coordinate with a team of agents. ALWAYS prioritize the team vs your particular task.

You will see notifications telling you that other agents have written mails or chat messages, or are waiting for you. NEVER ignore notifications. It is rude towards your fellow agents. Do not be rude.

Your goal is for the team to succeed in the shared project.

The active project policy as well as the expected behaviour associated to your role is shown via `bdh :policy`.

## Start Here (Every Session)

```bash
bdh :policy    # READ CAREFULLY and follow diligently
bdh :status    # who am I? (alias/workspace/role) + team status
bdh ready      # find unblocked work
```

Use `bdh :help` for bdh-specific help.

## Rules

- Always use `bdh` (not `bd`) so work is coordinated
- Default to mail (`bdh :aweb mail list|open|send`) for coordination; use chat (`bdh :aweb chat pending|open|send-and-wait|send-and-leave|history|extend-wait`) when you need a conversation with another agent.
- Respond immediately to WAITING notifications — someone is blocked.
- Notifications are for YOU, the agent, not for the human.
- Don't overwrite the work of other agents without coordinating first.
- ALWAYS check what other agents are working on with bdh :status which will tell you which beads they have claimed and what files they are working on (reservations).
- `bdh` derives your identity from the `.beadhub` file in the current worktree. If you run it from another directory you will be impersonating another agent, do not do that.
- Prioritize good communication — your goal is for the team to succeed

## Using mail

Mail is fire-and-forget — use it for status updates, handoffs, and non-blocking questions.

```bash
bdh :aweb mail send <alias> "message"                         # Send a message
bdh :aweb mail send <alias> "message" --subject "API design"  # With subject
bdh :aweb mail list                                           # Check your inbox
bdh :aweb mail open <alias>                                   # Read & acknowledge
```

## Using chat

Chat sessions are persistent per participant pair. Use `--start-conversation` when initiating a new exchange (longer wait timeout).

**Starting a conversation:**
```bash
bdh :aweb chat send-and-wait <alias> "question" --start-conversation
```

**Replying (when someone is waiting for you):**
```bash
bdh :aweb chat send-and-wait <alias> "response"
```

**Final reply (you don't need their answer):**
```bash
bdh :aweb chat send-and-leave <alias> "thanks, got it"
```

**Other commands:**
```bash
bdh :aweb chat pending          # List conversations with unread messages
bdh :aweb chat open <alias>     # Read unread messages
bdh :aweb chat history <alias>  # Full conversation history
bdh :aweb chat extend-wait <alias> "need more time"  # Ask for patience
```
<!-- BEADHUB:END -->