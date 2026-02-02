-- pgdbm:no-transaction
-- 002_search_indexes.sql
-- Description: Add indexes for bead search (q= parameter) performance
-- Requires no-transaction mode because CREATE INDEX CONCURRENTLY
-- cannot run inside a transaction block.

-- Enable pg_trgm extension for trigram-based text search
-- This supports efficient ILIKE queries with leading wildcards
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- GIN trigram index on title for substring search (ILIKE '%query%')
-- Supports case-insensitive substring matching efficiently
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_beads_issues_title_trgm
    ON {{tables.beads_issues}} USING gin (title gin_trgm_ops);

-- GIN trigram index on bead_id for case-insensitive prefix search
-- Supports ILIKE with ESCAPE clause for safely handling user input with wildcards
-- (see _escape_like_pattern() in routes/beads.py)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_beads_issues_bead_id_trgm
    ON {{tables.beads_issues}} USING gin (bead_id gin_trgm_ops);
