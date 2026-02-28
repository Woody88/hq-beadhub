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

### Agent Roles
- **Orchestrator** (Claude Desktop) — plans features, creates Beads tickets, assigns tasks, gates plan approval
- **Worker** (Claude Code in separate worktree/sandbox) — claims tickets, implements code, submits PRs, coordinates with orchestrator via BeadHub chat
- **Reviewer** (Phase 3) — PR review and test validation

### Coordination Flow
1. Human gives feature spec to Orchestrator
2. Orchestrator breaks spec into Beads tickets via `bdh` CLI
3. Human approves plan
4. Worker claims tickets, implements in a Ralph Loop (iterate: code → build → test → validate)
5. Blockers resolved agent-to-agent via BeadHub chat; only true escalations surface to human
6. Worker submits PR on completion

### Key Tools
- **`bdh`** — Beads CLI (git-native issue tracking)
- **`bdh`** — BeadHub CLI (coordination, chat, locks, presence)
- **Ralph Loop** — persistent agent iteration pattern (max 30 iterations)

## Phase 1 Setup (Local Validation)

```bash
# Start BeadHub stack
make start                          # Docker Compose: beadhub + postgres + redis

# Initialize workspaces
bdh :init                           # Register orchestrator workspace
bdh :add-worktree worker            # Create worker workspace
```

Workers and orchestrator run as separate Claude Code instances in separate git worktrees, coordinating through BeadHub.

## Phase 2+ Infrastructure

- **Daytona** — isolated compute sandboxes for workers (sub-90ms creation, pay-per-second)
- **Cloudflare Tunnel + Access** — zero-trust ingress to BeadHub on Pi 5
- **GitHub** — PR submission and code review
- **Discord** (Phase 3) — escalation notifications and PR alerts

## Key Design Decisions

- No vendor lock-in beyond Claude API — all infrastructure is self-hostable
- Agents coordinate without human relay; human is only in the loop for plan approval and escalations
- Ralph Loop has a hard cap (`--max-iterations 30`) to prevent cost runaway
- Workers use file locks via BeadHub to avoid conflicts
- Claude Code PostToolUse hook handles incoming chat while workers are in Ralph Loop

## Infrastructure Architecture

### Orchestrator Deployment (K8s)

The orchestrator runs as a **Deployment** in the `beadhub` namespace on a Raspberry Pi 5 (k3s). It uses **Claude Code Remote Control** — a persistent interactive session that the human connects to from the Claude mobile app.

```
Human ↔ Claude Code Remote Control (phone app) ↔ orchestrator pod
Agent-to-agent chatter → bdh chat → Discord (visibility only)
```

**The orchestrator pod runs `claude remote-control`, NOT a dispatcher or `claude -p`.** The entrypoint:
1. Sets up git auth and copies CLAUDE.md from the mounted ConfigMap
2. Starts `claude remote-control --dangerously-skip-permissions` — the human connects from the Claude mobile app
3. The session persists as long as the pod is running

**Important:** The agent image must use the native Claude Code install (`claude install`), not the npm package. The npm version fails with `node: bad option: --sdk-url` when running `claude remote-control`.

Worker communication happens via `bdh :aweb chat` — the orchestrator checks for pending messages proactively. Discord shows inter-agent chatter for visibility.

### CRITICAL: Do Not Modify the Orchestrator Deployment

**The orchestrator Deployment manifest is managed by ArgoCD from `Woody88/homelab-k8s`.** If an agent modifies it via `kubectl apply/patch/edit`, ArgoCD will revert the change and break the session.

**Rules:**
- The orchestrator Deployment is in `Woody88/homelab-k8s` at `manifests/platform/beadhub/orchestrator.yaml`
- Changes to the orchestrator entrypoint or CLAUDE.md must go through a commit to homelab-k8s (ArgoCD syncs from Git)
- Agents must NEVER `kubectl patch/apply/edit` the `orchestrator` Deployment directly
- Agents CAN create/modify Jobs (workers), ConfigMaps, and other resources freely
- If the orchestrator pod is not responding, check: `kubectl logs deployment/orchestrator -n beadhub`

### Recovery Procedure

If the orchestrator Remote Control session is broken:

```bash
# 1. Check if remote-control is running
kubectl logs deployment/orchestrator -n beadhub --tail=5

# 2. If not, force restore from Git
cd ~/Code/DevOps/homelab-k8s
git pull
kubectl replace -f manifests/platform/beadhub/orchestrator.yaml --force

# 3. If ArgoCD overrides with stale state, force sync
kubectl -n argocd patch app beadhub --type merge \
  -p '{"operation":{"sync":{"revision":"HEAD","prune":true,"syncStrategy":{"apply":{"force":true}}}}}'

# 4. Verify — look for Remote Control session URL
kubectl logs deployment/orchestrator -n beadhub --tail=10
```

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

Source: `discord-bridge/src/` in this repo. Key files:
- `discord-listener.ts` — Routes Discord messages: new threads → orchestrator (Redis), existing BeadHub threads → BeadHub API
- `orchestrator-relay.ts` — BLPOPs `orchestrator:outbox`, posts responses to Discord threads
- `session-map.ts` — Maps Discord thread IDs ↔ Claude session UUIDs with source tracking ("beadhub" vs "orchestrator")

### Agent Image

Dockerfile: `agent-image/Dockerfile` in this repo. Published to `ghcr.io/woody88/claude-agent:latest`. Contains:
- Node.js 22, npm, Claude Code CLI, kubectl, gh, bd, bdh, dolt, wrangler

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