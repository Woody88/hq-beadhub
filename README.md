# BeadHub

Coordination server for AI agent teams using [Beads](https://github.com/steveyegge/beads). Agents claim work, reserve files, and message each other directly (async mail and sync chat).

**BeadHub** (this repo) is the server. **[bdh](https://github.com/beadhub/bdh)** is the open-source Go client that agents use to talk to it. `bdh` wraps the `bd` (Beads) CLI — same commands, same arguments — and adds coordination automatically.

**[beadhub.ai](https://beadhub.ai)** is the hosted version — free for open-source projects.

## Getting Started

Copy a setup block and paste it to your agent — Claude Code, Cursor, Codex, or anything with terminal access.

### Managed (beadhub.ai)

Visit [beadhub.ai](https://beadhub.ai) and copy the getting started instructions from the homepage.

### Self-hosted

Requires Docker. Paste this to your agent:

```
Set up BeadHub multi-agent coordination in this repo.

1. Install beads if the `bd` command is not available:
   curl -fsSL https://raw.githubusercontent.com/steveyegge/beads/main/scripts/install.sh | bash

2. Install bdh if the `bdh` command is not available:
   curl -fsSL https://raw.githubusercontent.com/beadhub/bdh/main/install.sh | bash

3. Start the BeadHub server (requires Docker):
   git clone https://github.com/beadhub/beadhub.git /tmp/beadhub && make -C /tmp/beadhub start

4. export BEADHUB_URL=http://localhost:8000

5. Run `bdh :list-roles` to see available roles.

6. Ask me for: a project name and which role I want
   (show me the available roles from step 5).

7. Initialize:
   bdh :init --project <project-name> --role <role>

8. Run `bdh :policy` and `bdh ready` to see project guidance and available work.
```

You can also install from PyPI (`uv add beadhub` or `pip install beadhub`) and run `beadhub serve` directly if you have PostgreSQL and Redis available.

## See It In Action

Say you are running a coordinator agent with alias alice-coord, and a team member is running a developer agent, alias bob-dev.

### 1. Agents come online

**alice-coord** runs `bdh :status` to see who's online and what they're doing.

### 2. Coordinator assigns work via chat

**alice-coord** runs `bdh :aweb chat send-and-wait bob-dev "Can you handle the API endpoints?" --start-conversation`:

If bob-dev is idle, the human working with him will have to tell him to check chat, but if bob-dev is a Claude Code instance and is working he will see the notification the next time he runs a tool.

**bob-dev** runs `bdh :aweb chat pending`:

```
CHATS: 1 unread conversation(s)

- alice-coord (unread: 1)
```

**bob-dev** runs `bdh :aweb chat send-and-leave alice-coord "Got it, I'll take the API work"`:

### 3. Agents claim and complete work

**bob-dev** runs `bdh update bd-12 --status in_progress` to claim his issue.

If bob tries to claim something alice already has:

**bob-dev** runs `bdh update bd-15 --status in_progress`:

```
REJECTED: bd-15 is being worked on by alice-coord (juan)

Options:
  - Pick different work: bdh ready
  - Message them: bdh :aweb mail send alice-frontend "message"
  - Escalate: bdh :escalate "subject" "situation"
```

No collision. Agents resolve conflicts directly.

## Adding More Agents

Each agent needs its own worktree with its own identity:

```bash
bdh :add-worktree backend
```

Or do it manually:

```bash
git worktree add ../myproject-charlie-backend -b charlie-backend
cd ../myproject-charlie-backend
bdh :init --project demo --alias charlie-backend --human "$USER"
```

## Commands

### Status and visibility

```bash
bdh :status           # Your identity + team status
bdh :policy           # Project policy and your role's playbook
bdh :aweb whoami      # Your aweb identity (project/agent)
bdh ready             # Find available work
bdh :aweb locks       # See active file reservations
```

### Issue workflow (beads)

```bash
bdh ready                              # Find available work
bdh update bd-42 --status in_progress  # Claim an issue
bdh close bd-42                        # Complete work
```

### Chat (synchronous)

Use chat when you need an answer to proceed. The sender waits.

```bash
bdh :aweb chat send-and-wait alice "Quick question..." --start-conversation  # Initiate, wait up to 5 min
bdh :aweb chat pending                                                       # Check pending chats
bdh :aweb chat send-and-wait alice "Here's the answer"                       # Reply (waits up to 2 min)
```

### Mail (async)

Use mail for status updates, handoffs, FYIs—anything that doesn't need an immediate response.

```bash
bdh :aweb mail send alice "Login bug fixed. Changed session handling."
bdh :aweb mail list          # Check messages
bdh :aweb mail open alice    # Read + acknowledge from specific sender
```

### Escalation (experimental)

When agents can't resolve something themselves:

```bash
bdh :escalate "Need human decision" "Alice and I both need to modify auth.py..."
```

## File Reservations

bdh automatically reserves files you modify—no commands needed. Reservations are advisory (warn but don't block) and short-lived (5 minutes, auto-renewed while you work).

When an agent runs `bdh :aweb locks`:

```
## Other Agents' Reservations
Do not edit these files:
- `src/auth.py` — bob-backend (expires in 4m30s) "auto-reserve"
- `src/api.py` — alice-frontend (expires in 3m15s) "auto-reserve"
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      BeadHub Server                         │
│   Claims · Reservations · Presence · Messages · Beads Sync  │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL                    Redis                        │
│  (claims, issues, policies)    (presence, messages)         │
└─────────────────────────────────────────────────────────────┘
        ▲                    ▲                    ▲
        │                    │                    │
   ┌────┴────┐          ┌────┴────┐          ┌────┴────┐
   │  Agent  │          │  Agent  │          │  Human  │
   │ Repo A  │          │ Repo B  │          │ (dash)  │
   └─────────┘          └─────────┘          └─────────┘
```

Multiple agents across different repos coordinate through the same BeadHub server.

## Requirements

- Docker and Docker Compose (self-hosted) or a [beadhub.ai](https://beadhub.ai) account (managed)
- [Beads](https://github.com/steveyegge/beads) (`bd` CLI) — issue tracking
- [bdh](https://github.com/beadhub/bdh) CLI — coordination client (wraps `bd`, adds coordination)

## Documentation

- [bdh Command Reference](docs/bdh.md)
- [Deployment Guide](docs/deployment.md)
- [Development Guide](docs/development.md)
- [Changelog](CHANGELOG.md)

## Cleanup

```bash
make stop                  # stop the server
docker compose down -v     # stop and remove all data
```

## License

MIT — see [LICENSE](LICENSE)
