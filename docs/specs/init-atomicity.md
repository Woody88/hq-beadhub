# /v1/init Atomicity (Transactional Bootstrap)

`POST /v1/init` bootstraps an OSS deployment by creating or restoring:

- a project (by `project_slug`)
- a repo (by `repo_origin` / `canonical_origin`)
- a workspace (by `alias`)
- a new project API key (`aw_sk_...`)
- a default policy bundle (if missing)

## Problem

Without an explicit transaction, a failure mid-flow (e.g., workspace insert conflict, API key insert failure) can persist earlier rows and leave partially-created resources.

This is both a correctness issue (idempotency becomes surprising) and an operational risk (operators may need manual cleanup).

## Decision

Wrap all server DB mutations inside a single DB transaction:

- Any failure results in a full rollback (no partial project/repo/workspace/key/policy rows).
- Rate limiting remains outside the transaction.

## Implementation

- `src/beadhub/routes/init.py:init_workspace` uses `async with server_db.transaction():` to scope:
  - project restore/create
  - repo upsert
  - workspace lookup/insert
  - api key insert
  - policy bootstrap (`get_active_policy`)

## Acceptance Criteria

- Induce a failure mid-flow (e.g., force a unique violation on workspace insert or api key insert) and verify no new rows exist for project/repo/workspace/api_keys.
- Existing workspace init remains idempotent (returns existing `workspace_id` but issues a new API key).
- The “atomic” claim remains accurate (transactional) in code/docs.
