# BeadHub

Multi-agent coordination server for AI coding assistants. Provides workspace registration, file locking, messaging (mail + chat), and policy management.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, PostgreSQL (via pgdbm)
- **Package Manager**: uv (Python)

## Project Structure

```
src/beadhub/          # Python server
  routes/             # FastAPI endpoints
  defaults/           # Policy defaults (markdown files)
```

## Development

**Run server:**
```bash
uv run beadhub
```

**Run tests:**
```bash
uv run pytest              # Python tests
```

## Key Concepts

- **Workspace**: An agent instance registered with a project (has alias, role, human name)
- **Policy**: Project-level invariants + role playbooks that guide agent behavior
- **Mail**: Async messages between workspaces (`bdh :aweb mail send <alias> "message"`)
- **Chat**: Sync conversations with wait/reply semantics (`bdh :aweb chat send <alias> "message" --start-conversation`)
- **Reservations**: File locks to prevent edit conflicts

## Architecture Notes

- Server uses pgdbm for PostgreSQL with template-based table naming. Make sure to use your pgdbm skill and to understand the test fixtures offered by pgdbm b
efore makign or changing any tests.

- CLI wraps `bdh` (beads) for issue tracking, adds coordination features
- Policy defaults loaded from markdown files at startup (hot-reload via reset endpoint)
- Auth uses per-project API keys (client sends `Authorization: Bearer ...`); bootstrap via `bdh :init` / `POST /v1/init`

- ALWAYS do a code-reviewer run before closing a bead.



<!-- BEADHUB:START -->
## BeadHub Coordination

This project uses `bdh` for multi-agent coordination. Run `bdh :policy` for instructions.

```bash
bdh :status    # your identity + team status
bdh :policy    # READ AND FOLLOW
bdh ready      # find work
```
<!-- BEADHUB:END -->