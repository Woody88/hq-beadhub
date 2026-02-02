from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pgdbm import AsyncDatabaseManager

logger = logging.getLogger(__name__)

# Bead ID format: alphanumeric with common separators, 1-100 chars
# Examples: bd-abc123, myproject-xyz, issue-42, pgdbm-4uv.16
BEAD_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")

# Git branch name pattern: alphanumeric with common separators, 1-255 chars
# Examples: main, feature/new-ui, release/v1.0.0, bugfix/issue-123
BRANCH_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_.-]{0,254}$")

# Canonical origin pattern: domain/path format like "github.com/org/repo"
# Allows alphanumeric, dots, hyphens, underscores, and forward slashes.
# Each path segment must start with alphanumeric (prevents ".." traversal).
# Max length 255 (checked in validator function).
# Examples: github.com/org/repo, gitlab.example.com/team/project
CANONICAL_ORIGIN_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*(/[a-zA-Z0-9][a-zA-Z0-9._-]*)*$")

# Alias pattern: alphanumeric with hyphens/underscores, 1-64 chars
# Examples: frontend-bot, backend_agent, claude-code-1
ALIAS_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

# Human name pattern: letters with spaces, hyphens, apostrophes, 1-64 chars
# Examples: Juan, O'Brien, Mary Jane, Jean-Pierre
HUMAN_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9 '\-]{0,63}$")

# Default values for repo and branch when not specified
DEFAULT_REPO = "default"
DEFAULT_BRANCH = "main"


def is_valid_bead_id(bead_id: str) -> bool:
    """Check if bead ID matches expected format."""
    if not bead_id or not isinstance(bead_id, str):
        return False
    return BEAD_ID_PATTERN.match(bead_id) is not None


def is_valid_branch_name(branch: str) -> bool:
    """Check if branch name matches expected Git branch format."""
    if not branch or not isinstance(branch, str):
        return False
    return BRANCH_NAME_PATTERN.match(branch) is not None


def is_valid_canonical_origin(origin: str) -> bool:
    """Check if canonical origin matches expected format (e.g., github.com/org/repo)."""
    if not origin or not isinstance(origin, str):
        return False
    if len(origin) > 255:
        return False
    return CANONICAL_ORIGIN_PATTERN.match(origin) is not None


def is_valid_alias(alias: str) -> bool:
    """Check if alias matches expected format."""
    if not alias or not isinstance(alias, str):
        return False
    return ALIAS_PATTERN.match(alias) is not None


def is_valid_human_name(name: str) -> bool:
    """Check if human name matches expected format."""
    if not name or not isinstance(name, str):
        return False
    return HUMAN_NAME_PATTERN.match(name) is not None


@dataclass
class BeadStatusChange:
    """Represents a status change for notification purposes."""

    bead_id: str
    repo: Optional[str]
    branch: Optional[str]
    old_status: Optional[str]
    new_status: str
    title: Optional[str] = None


@dataclass
class BeadsSyncResult:
    issues_synced: int
    issues_added: int
    issues_updated: int
    synced_at: str
    repo: Optional[str] = None
    branch: Optional[str] = None
    status_changes: List["BeadStatusChange"] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)  # bead IDs that had stale updates

    @property
    def conflicts_count(self) -> int:
        return len(self.conflicts)


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def validate_issues_from_list(issues_list: List[Any]) -> Dict[str, dict[str, Any]]:
    """
    Validate issues from a list (e.g., from an upload payload).

    Args:
        issues_list: List of issue dictionaries

    Returns:
        Dictionary mapping issue IDs to validated issue records.
        Invalid issues are skipped with a warning.
    """
    issues: Dict[str, dict[str, Any]] = {}

    for idx, record in enumerate(issues_list):
        if not isinstance(record, dict):
            logger.warning("Skipping non-dict issue at index %d", idx)
            continue

        issue_id = record.get("id")
        if not issue_id:
            logger.warning("Skipping record without 'id' at index %d", idx)
            continue

        if not is_valid_bead_id(issue_id):
            logger.warning(
                "Skipping record with invalid bead ID '%s' at index %d",
                issue_id[:50] if isinstance(issue_id, str) else str(issue_id)[:50],
                idx,
            )
            continue

        issues[issue_id] = record

    return issues


def _parse_dependency_ref(
    depends_on: str, default_repo: str, default_branch: str
) -> Optional[dict]:
    """Parse a dependency reference into {repo, branch, bead_id}.

    If depends_on contains ':', treat as cross-repo ref (repo:bead_id).
    Otherwise, use the default repo/branch from current sync context.

    Returns None if the reference is malformed (empty repo, invalid bead_id).
    """
    depends_on = depends_on.strip()
    if not depends_on:
        return None

    if ":" in depends_on:
        # Cross-repo reference like "other-repo:bd-123"
        # Use default branch since cross-repo refs don't specify branch
        ref_repo, ref_bead_id = depends_on.split(":", 1)
        ref_repo = ref_repo.strip()
        ref_bead_id = ref_bead_id.strip()
        if not ref_repo or not is_valid_bead_id(ref_bead_id):
            logger.warning("Malformed cross-repo dependency ref: %r", depends_on)
            return None
        if not is_valid_canonical_origin(ref_repo):
            logger.warning("Invalid repo in cross-repo dependency ref: %r", ref_repo)
            return None
        return {"repo": ref_repo, "branch": default_branch, "bead_id": ref_bead_id}
    else:
        # Same-repo reference
        if not is_valid_bead_id(depends_on):
            logger.warning("Invalid bead ID in dependency ref: %r", depends_on)
            return None
        return {"repo": default_repo, "branch": default_branch, "bead_id": depends_on}


def _parse_structured_ref(item: dict, default_repo: str, default_branch: str) -> Optional[dict]:
    """Parse a structured blocked_by dict into {repo, branch, bead_id}.

    Accepts: {"repo": "...", "branch": "...", "bead_id": "..."}
    repo and branch are optional and default to the sync context values.
    bead_id is required and must be valid.

    Returns None if bead_id is missing/invalid, or if repo/branch are invalid.
    """
    bead_id = item.get("bead_id")
    if not bead_id or not is_valid_bead_id(bead_id):
        if bead_id:
            logger.warning("Invalid bead_id in structured blocked_by: %r", bead_id)
        else:
            logger.warning("Missing bead_id in structured blocked_by: %r", item)
        return None

    # Validate repo if provided
    repo = item.get("repo")
    if repo and not is_valid_canonical_origin(repo):
        logger.warning("Invalid repo in structured blocked_by: %r", repo)
        return None

    # Validate branch if provided
    branch = item.get("branch")
    if branch and not is_valid_branch_name(branch):
        logger.warning("Invalid branch name in structured blocked_by: %r", branch)
        return None

    return {
        "repo": repo or default_repo,
        "branch": branch or default_branch,
        "bead_id": bead_id,
    }


def parse_blocked_by_array(
    blocked_by: Optional[list], default_repo: str, default_branch: str
) -> List[dict]:
    """Parse a blocked_by array into structured refs.

    Accepts two formats:
    1. Structured dicts: [{"repo": "...", "branch": "...", "bead_id": "..."}]
       - repo and branch are optional, default to sync context
       - bead_id is required
    2. Simple strings: ["bd-001", "other-repo:bd-002"]
       - Same-repo refs use defaults
       - Cross-repo refs use "repo:bead_id" format

    Returns list of {repo, branch, bead_id} dicts.
    Invalid entries are skipped with a warning.
    """
    if not blocked_by:
        return []

    refs = []
    for item in blocked_by:
        if isinstance(item, dict):
            ref = _parse_structured_ref(item, default_repo, default_branch)
        elif isinstance(item, str):
            ref = _parse_dependency_ref(item, default_repo, default_branch)
        else:
            logger.warning("Unexpected type in blocked_by array: %r", type(item).__name__)
            continue

        if ref is not None:
            refs.append(ref)
    return refs


async def _sync_issues_to_db(
    issues: Dict[str, dict],
    db: AsyncDatabaseManager,
    project_id: str,
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
) -> BeadsSyncResult:
    """
    Sync parsed issues to the database.

    Args:
        issues: Dictionary mapping issue IDs to issue records
        db: Database manager for beads schema
        project_id: UUID of the project (tenant isolation)
        repo: Canonical origin for this sync (e.g., 'github.com/org/repo')
        branch: Git branch name for this sync (default: 'main')
    """
    now = datetime.now(timezone.utc)
    issues_added = 0
    issues_updated = 0
    status_changes: List[BeadStatusChange] = []
    conflicts: List[str] = []  # bead IDs with stale updates

    async with db.transaction() as tx:
        for bead_id, issue in issues.items():
            status = issue.get("status")
            title = issue.get("title")
            description = issue.get("description")
            priority = issue.get("priority")
            issue_type = issue.get("issue_type")
            assignee = issue.get("assignee")
            created_by = issue.get("created_by")
            if created_by is not None and not isinstance(created_by, str):
                created_by = str(created_by)
            if isinstance(created_by, str):
                created_by = created_by.strip() or None
                if created_by and len(created_by) > 255:
                    logger.warning(
                        "Truncating created_by for %s (len=%d)", bead_id, len(created_by)
                    )
                    created_by = created_by[:255]
            labels = issue.get("labels") or None

            created_at = _parse_timestamp(issue.get("created_at"))
            updated_at = _parse_timestamp(issue.get("updated_at"))

            deps = issue.get("dependencies") or []
            parent_id: Optional[dict] = None

            # Support simple blocked_by array from spec: ["bd-001", "bd-002"]
            simple_blocked_by = issue.get("blocked_by")
            blocked_by: List[dict] = parse_blocked_by_array(simple_blocked_by, repo, branch)

            # Also process structured dependencies format
            for dep in deps:
                dep_type = dep.get("type")
                depends_on = dep.get("depends_on_id")
                if not depends_on:
                    continue

                ref = _parse_dependency_ref(depends_on, repo, branch)
                if ref is None:
                    continue

                if dep_type == "parent-child":
                    if parent_id is None:
                        parent_id = ref
                    continue  # parent-child is not a blocking relationship

                if dep_type != "blocks":
                    continue

                target = issues.get(depends_on)
                target_status = target.get("status") if target else None
                if target_status != "closed":
                    blocked_by.append(ref)

            existing = await tx.fetch_one(
                """
                SELECT bead_id, status, updated_at FROM {{tables.beads_issues}}
                WHERE project_id = $1 AND bead_id = $2 AND repo = $3 AND branch = $4
                FOR UPDATE
                """,
                project_id,
                bead_id,
                repo,
                branch,
            )

            if existing is None:
                issues_added += 1
                # New issue - track as status change from None to current status
                if status:
                    status_changes.append(
                        BeadStatusChange(
                            bead_id=bead_id,
                            repo=repo,
                            branch=branch,
                            old_status=None,
                            new_status=status,
                            title=title,
                        )
                    )
            else:
                # Optimistic locking: check if incoming update is stale
                db_updated_at = existing.get("updated_at")
                if updated_at is not None and db_updated_at is not None:
                    # Both have timestamps - compare them
                    if updated_at < db_updated_at:
                        # Stale update - skip and record conflict
                        logger.info(
                            "Stale update detected for %s: incoming %s < DB %s",
                            bead_id,
                            updated_at.isoformat(),
                            db_updated_at.isoformat(),
                        )
                        conflicts.append(bead_id)
                        continue  # Skip this issue, don't update

                issues_updated += 1
                # Check if status changed
                old_status = existing.get("status")
                if old_status != status and status:
                    status_changes.append(
                        BeadStatusChange(
                            bead_id=bead_id,
                            repo=repo,
                            branch=branch,
                            old_status=old_status,
                            new_status=status,
                            title=title,
                        )
                    )

            await tx.execute(
                """
                INSERT INTO {{tables.beads_issues}} (
                    project_id,
                    bead_id,
                    repo,
                    branch,
                    title,
                    description,
                    status,
                    priority,
                    issue_type,
                    assignee,
                    created_by,
                    labels,
                    blocked_by,
                    parent_id,
                    created_at,
                    updated_at,
                    synced_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17
                )
                ON CONFLICT (project_id, repo, branch, bead_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    issue_type = EXCLUDED.issue_type,
                    assignee = EXCLUDED.assignee,
                    created_by = COALESCE(EXCLUDED.created_by, {{tables.beads_issues}}.created_by),
                    labels = EXCLUDED.labels,
                    blocked_by = EXCLUDED.blocked_by,
                    parent_id = EXCLUDED.parent_id,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    synced_at = EXCLUDED.synced_at
                """,
                project_id,
                bead_id,
                repo,
                branch,
                title,
                description,
                status,
                priority,
                issue_type,
                assignee,
                created_by,
                labels,
                # asyncpg requires JSON strings for JSONB columns (no auto-serialization)
                json.dumps(blocked_by),
                json.dumps(parent_id) if parent_id else None,
                created_at,
                updated_at,
                now,
            )

    return BeadsSyncResult(
        issues_synced=len(issues),
        issues_added=issues_added,
        issues_updated=issues_updated,
        synced_at=now.isoformat(),
        repo=repo,
        branch=branch,
        status_changes=status_changes,
        conflicts=conflicts,
    )


async def delete_issues_by_id(
    db: AsyncDatabaseManager,
    project_id: str,
    bead_ids: List[str],
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
) -> int:
    """
    Delete issues by their IDs.

    Args:
        db: Database manager for beads schema
        project_id: UUID of the project (tenant isolation)
        bead_ids: List of bead IDs to delete
        repo: Canonical origin for this sync (e.g., 'github.com/org/repo')
        branch: Git branch name for this sync

    Returns:
        Number of issues deleted
    """
    if not bead_ids:
        return 0

    # Validate all bead IDs first
    valid_ids = [bid for bid in bead_ids if is_valid_bead_id(bid)]
    if len(valid_ids) != len(bead_ids):
        invalid_count = len(bead_ids) - len(valid_ids)
        logger.warning("Skipping %d invalid bead IDs in delete request", invalid_count)

    if not valid_ids:
        return 0

    async with db.transaction() as tx:
        # Delete issues matching the IDs
        result = await tx.execute(
            """
            DELETE FROM {{tables.beads_issues}}
            WHERE project_id = $1
              AND repo = $2
              AND branch = $3
              AND bead_id = ANY($4::text[])
            """,
            project_id,
            repo,
            branch,
            valid_ids,
        )

        # Parse the result to get count (asyncpg returns "DELETE N")
        if result and result.startswith("DELETE "):
            return int(result.split()[1])
        return 0
