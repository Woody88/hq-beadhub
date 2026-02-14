# beadhub — Source of Truth

Open-source coordination server for AI coding agents. Agents register workspaces, claim work, exchange messages, lock files, follow policies, and sync issues — all scoped per project.

## Ecosystem

beadhub is one piece of a larger system:

- **aweb** (Python package) — Agent coordination protocol. Provides identity, API keys, mail, chat, file locks, and presence. beadhub embeds aweb as a library: aweb routers are mounted directly into the FastAPI app, and aweb tables live in the same Postgres database under the `aweb` schema.
- **bdh** (Go CLI, separate repo) — The client that agents use. Wraps `bd` (beads issue tracker) and adds coordination commands (`:status`, `:policy`, `:aweb mail`, `:aweb chat`). Talks to beadhub over HTTP.
- **beadhub-cloud** — Managed SaaS wrapper. Mounts beadhub at `/api/v1`, adds user accounts, billing, and proxy authentication. Not open-source.

beadhub can run **standalone** (direct API key auth) or **embedded in beadhub-cloud** (proxy header auth). The codebase handles both modes transparently.

## Stack

- **Python 3.12+**, FastAPI, uvicorn
- **PostgreSQL** via pgdbm (schema-isolated, template-based table naming)
- **Redis** (presence cache, file locks, pub/sub for real-time events)
- **Package manager**: always `uv` (never pip)

## Core Concepts

### Project
Tenant boundary. All data is scoped by `project_id`. A project has a slug, name, visibility, and an active policy. In multi-tenant (Cloud) mode, projects also have a `tenant_id`.

### Workspace
An agent's working context within a project. Has `workspace_id`, `alias`, `role`, `human_name`, and is tied to a git repo. In v1, `workspace_id == agent_id` (aweb identity). Immutable links: workspace→project and workspace→repo never change after creation. Soft-deleted via `deleted_at`.

### Repo
A git repository tracked by beadhub, identified by `canonical_origin` (e.g., `github.com/org/repo`). Unique per project. Soft-deleted.

### Bead (Issue)
An issue synced from the client's `.beads/issues.jsonl` file via `POST /v1/bdh/sync`. Has `bead_id`, `title`, `status`, `priority`, `assignee`, `labels`, `blocked_by` (cross-repo dependencies as JSONB). The server stores beads but the client is the authority — sync is a client-push model.

### Claim
Who's working on which bead. A workspace claims a bead during sync. Multiple agents can claim the same bead (coordinated work). Claims track `apex_bead_id` for molecule (parent issue) context.

### Policy
Project-scoped, versioned bundle of invariants (rules for all agents) and role playbooks (role-specific guidance). Stored as JSONB. Defaults loaded from markdown files in `src/beadhub/defaults/` at startup. Supports optimistic concurrency: `base_policy_id` in create request triggers a 409 if the active policy changed since the caller last read it.

### Escalation
A request for human intervention. An agent describes a situation, provides options, and waits for a response. Has status lifecycle: pending → responded | expired.

### Subscription
An agent subscribes to status changes on specific beads. When a bead's status changes during sync, the notification outbox queues a mail to each subscriber.

## Authentication

Two modes, selected automatically based on request headers:

### Bearer Mode (standalone / direct)
Client sends `Authorization: Bearer aw_sk_...`. The token is verified against the aweb `api_keys` table. Extracts `project_id`, `agent_id`, and `api_key_id`. Actor binding is enforced: the `agent_id` in the token must match any `workspace_id` claimed in the request body.

### Proxy Mode (beadhub-cloud)
Cloud wrapper injects signed headers: `X-BH-Auth` (HMAC-SHA256 signature), `X-Project-ID`, `X-User-ID` or `X-API-Key`, `X-Aweb-Actor-ID`. Requires `BEADHUB_INTERNAL_AUTH_SECRET` env var. Principal types: `u` (user), `k` (API key), `p` (public reader — read-only, PII redacted).

### Key functions
- `get_project_from_auth(request, db)` → project_id (for read-only endpoints)
- `get_identity_from_auth(request, db)` → AuthIdentity (for write endpoints)
- `enforce_actor_binding(identity, workspace_id)` → 403 if mismatch in bearer mode
- `is_public_reader(request)` → True if signed proxy with principal_type="p"

## Database Architecture

Three pgdbm schemas share one Postgres database with a single connection pool:

### `aweb` schema (managed by aweb library)
Projects, agents, API keys, messages, chat conversations, chat messages, reservations. Migrations live in the aweb package.

### `server` schema (beadhub's own)
| Table | Purpose |
|-------|---------|
| `projects` | Project root. Has `active_policy_id` FK, `visibility`, `tenant_id` |
| `repos` | Git repos. Unique `canonical_origin` per project |
| `workspaces` | Agent instances. Alias unique per project (partial index on non-deleted) |
| `bead_claims` | Active work claims. FK to workspace and project |
| `escalations` | Human escalation requests with response lifecycle |
| `subscriptions` | Bead status change notification subscriptions |
| `notification_outbox` | Outbox pattern for reliable notification delivery |
| `audit_log` | Event trail (sync events, policy changes, etc.) |
| `project_policies` | Versioned policy bundles (JSONB). Unique (project_id, version) |

### `beads` schema
| Table | Purpose |
|-------|---------|
| `beads_issues` | Synced issues. Cross-repo `blocked_by` as JSONB. GIN trigram indexes for search |

### pgdbm patterns
All queries use template syntax: `{{tables.workspaces}}` resolves to `server.workspaces`. Access a schema's manager via `db_infra.get_manager("server")`. Migrations live in `src/beadhub/migrations/{schema}/`. The aweb schema migrations are in the aweb package itself.

### Key database patterns
- **Project scoping**: every query filters by `project_id`
- **Soft-delete**: repos and workspaces use `deleted_at` timestamps, never hard-deleted
- **Immutable links**: workspace→project, workspace→repo, repo→project enforced by trigger
- **Atomic versioning**: policy version numbers allocated under `FOR UPDATE` row lock
- **Outbox pattern**: notifications written to `notification_outbox`, processed asynchronously

## Redis Usage

- **Presence**: `presence:{workspace_id}` hash with secondary indexes for lookup by project, repo, branch, alias. TTL 30 minutes (indexes 60 minutes).
- **Real-time events**: pub/sub channels for SSE streaming. Event types: reservation, message, escalation, bead.
- **File locks**: aweb reservations use Redis for lock state.
- Redis is ephemeral — Postgres is authoritative for all persistent data.

## API Surface

### aweb protocol endpoints (mounted from aweb library)
`/v1/auth/*`, `/v1/chat/*`, `/v1/messages/*`, `/v1/projects/*`, `/v1/reservations/*`

### beadhub endpoints

| Route file | Prefix | What it does |
|------------|--------|-------------|
| `init.py` | `POST /v1/init` | Bootstrap: create aweb agent + beadhub workspace in one call |
| `workspaces.py` | `/v1/workspaces` | Register, list, get, patch, soft-delete workspaces |
| `repos.py` | `/v1/repos` | Register, list, delete repos |
| `agents.py` | `/v1/agents` | Agent presence list, alias prefix suggestions |
| `beads.py` | `/v1/beads` | Issue upload (JSONL), list, get, ready (unblocked) |
| `bdh.py` | `/v1/bdh` | CLI sync (issues + claims + notifications), command pre-flight |
| `claims.py` | `/v1/claims` | List active bead claims |
| `policies.py` | `/v1/policies` | CRUD policy versions, activate, reset to defaults, history |
| `escalations.py` | `/v1/escalations` | Create, list, get, respond to escalations |
| `subscriptions.py` | `/v1/subscriptions` | Subscribe/unsubscribe to bead status changes |
| `status.py` | `/v1/status` | Workspace status snapshot + SSE stream |

### The sync endpoint (`POST /v1/bdh/sync`)
The most important endpoint. Called by `bdh sync`. Accepts full (`issues_jsonl`) or incremental (`changed_issues` + `deleted_ids`) payloads. Upserts issues, updates claims, processes notification outbox, and returns sync stats. This is the primary data flow from client to server.

## Codebase Layout

```
src/beadhub/
  __init__.py          # Exports create_app(), main()
  api.py               # App factory, mounts aweb + beadhub routers, lifespan
  config.py            # Environment variable settings
  db.py                # DatabaseInfra: pgdbm pool + 3 schema managers
  auth.py              # Actor binding, workspace access verification
  aweb_introspection.py # Bearer + proxy auth → AuthIdentity
  internal_auth.py     # Proxy header parsing + HMAC verification
  presence.py          # Redis presence cache with secondary indexes
  notifications.py     # Outbox processing → aweb mail delivery
  events.py            # Redis pub/sub event bus for SSE
  beads_sync.py        # Issue sync logic, validation, status change tracking
  defaults.py          # Load policy defaults from markdown files
  routes/              # FastAPI endpoint modules (see API Surface above)
  migrations/
    server/            # Server schema migrations
    beads/             # Beads schema migrations
  defaults/
    invariants/        # Default policy invariants (numbered markdown files)
    roles/             # Default role playbooks (markdown files)
```

## App Startup

`create_app()` in `api.py` supports two modes:

- **Standalone**: no args → creates its own Postgres pool and Redis connection, runs migrations, manages lifecycle.
- **Library**: pass `db_infra` and `redis` → uses externally managed connections. Used by beadhub-cloud to embed beadhub in a larger app.

aweb routers are mounted first (auth, chat, messages, projects, reservations), then beadhub's own routers. beadhub overrides `/v1/init` with an extended version that creates both an aweb agent and a beadhub workspace atomically.

## Test Infrastructure

Tests use pgdbm's `AsyncTestDatabase` for isolated test databases. Key fixtures in `tests/conftest.py`:

- `db_infra` — fresh DatabaseInfra with all migrations applied
- `test_db_with_schema` — bare pgdbm manager for low-level schema tests
- `beadhub_server` — full server subprocess on port 18765. Integration tests use `httpx` against this.
- `init_workspace()` — factory that calls `/v1/init` + `/v1/workspaces/register` and returns `(project_id, api_key)`
- Redis tests use database 15 (`redis://localhost:6379/15`)

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `BEADHUB_DATABASE_URL` or `DATABASE_URL` | (required) | Postgres connection |
| `BEADHUB_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `BEADHUB_HOST` | `0.0.0.0` | Server bind address |
| `BEADHUB_PORT` | `8000` | Server port |
| `BEADHUB_LOG_LEVEL` | `info` | Log level |
| `BEADHUB_PRESENCE_TTL_SECONDS` | `1800` | Presence cache TTL |
| `BEADHUB_INTERNAL_AUTH_SECRET` | (none) | Enables proxy auth when set |
