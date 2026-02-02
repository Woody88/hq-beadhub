-- 001_initial.sql
-- Description: Baseline BeadHub beads schema (issues)

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS {{tables.beads_issues}} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Tenant isolation: project_id scopes all data
    project_id UUID NOT NULL,

    -- Identity: bead_id is unique within (project_id, repo, branch)
    bead_id TEXT NOT NULL,
    repo TEXT NOT NULL DEFAULT 'default',  -- canonical origin e.g. github.com/org/repo
    branch TEXT NOT NULL DEFAULT 'main',

    -- Issue content
    title TEXT,
    description TEXT,
    status TEXT,
    priority INTEGER,
    issue_type TEXT,
    assignee TEXT,
    labels TEXT[],

    -- Dependencies as JSONB for cross-repo/branch references
    blocked_by JSONB DEFAULT '[]'::jsonb,
    parent_id JSONB,

    -- Creator attribution
    created_by TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ DEFAULT NOW(),

    -- Bead history: who closed this bead (cross-schema FK to server.workspaces)
    closed_by_workspace_id UUID REFERENCES server.workspaces(workspace_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_beads_issues_project_repo_branch_bead
    ON {{tables.beads_issues}}(project_id, repo, branch, bead_id);

CREATE INDEX IF NOT EXISTS idx_beads_issues_project_id
    ON {{tables.beads_issues}}(project_id);

CREATE INDEX IF NOT EXISTS idx_beads_issues_status
    ON {{tables.beads_issues}}(status);

CREATE INDEX IF NOT EXISTS idx_beads_issues_project_repo
    ON {{tables.beads_issues}}(project_id, repo);

CREATE INDEX IF NOT EXISTS idx_beads_issues_parent
    ON {{tables.beads_issues}}((parent_id->>'bead_id'))
    WHERE parent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_beads_issues_project_bead
    ON {{tables.beads_issues}}(project_id, bead_id);

CREATE INDEX IF NOT EXISTS idx_beads_issues_closed_by
    ON {{tables.beads_issues}}(closed_by_workspace_id)
    WHERE closed_by_workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_beads_issues_project_status
    ON {{tables.beads_issues}}(project_id, status);

CREATE INDEX IF NOT EXISTS idx_beads_issues_project_created_by
    ON {{tables.beads_issues}}(project_id, created_by)
    WHERE created_by IS NOT NULL;
