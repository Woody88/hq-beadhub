-- 002_add_projects_visibility.sql
-- Description: Add project visibility to support public/private projects.
--
-- This is an additive migration to keep upgrades safe for databases created
-- before `visibility` existed on server.projects.

ALTER TABLE {{tables.projects}}
ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

DO $$
BEGIN
    ALTER TABLE {{tables.projects}}
    ADD CONSTRAINT projects_visibility_check
    CHECK (visibility IN ('private', 'public'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

