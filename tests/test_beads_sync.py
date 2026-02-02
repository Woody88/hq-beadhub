"""Unit tests for beads_sync module."""

from beadhub.beads_sync import _parse_dependency_ref


def test_parse_dependency_ref_valid_same_repo():
    """Valid same-repo reference returns correct dict."""
    result = _parse_dependency_ref("bd-123", "myrepo", "main")
    assert result == {"repo": "myrepo", "branch": "main", "bead_id": "bd-123"}


def test_parse_dependency_ref_valid_cross_repo():
    """Valid cross-repo reference returns correct dict."""
    result = _parse_dependency_ref("other-repo:bd-456", "myrepo", "main")
    assert result == {"repo": "other-repo", "branch": "main", "bead_id": "bd-456"}


def test_parse_dependency_ref_empty_string():
    """Empty string returns None."""
    assert _parse_dependency_ref("", "myrepo", "main") is None
    assert _parse_dependency_ref("   ", "myrepo", "main") is None


def test_parse_dependency_ref_empty_repo():
    """Empty repo in cross-repo ref returns None."""
    assert _parse_dependency_ref(":bd-123", "myrepo", "main") is None


def test_parse_dependency_ref_empty_bead_id():
    """Empty bead_id in cross-repo ref returns None."""
    assert _parse_dependency_ref("repo:", "myrepo", "main") is None


def test_parse_dependency_ref_multiple_colons():
    """Multiple colons (invalid bead_id) returns None."""
    # "repo:branch:bd-123" would parse as repo="repo", bead_id="branch:bd-123"
    # which is invalid because bead_id contains a colon
    assert _parse_dependency_ref("repo:branch:bd-123", "myrepo", "main") is None


def test_parse_dependency_ref_invalid_bead_id():
    """Invalid bead_id format returns None."""
    assert _parse_dependency_ref("../../../etc/passwd", "myrepo", "main") is None
    assert _parse_dependency_ref("repo:../bad", "myrepo", "main") is None


def test_parse_simple_blocked_by_format():
    """Simple blocked_by array should be parsed correctly."""
    from beadhub.beads_sync import parse_blocked_by_array

    # Simple same-repo blockers
    result = parse_blocked_by_array(["bd-001", "bd-002"], "myrepo", "main")
    assert result == [
        {"repo": "myrepo", "branch": "main", "bead_id": "bd-001"},
        {"repo": "myrepo", "branch": "main", "bead_id": "bd-002"},
    ]


def test_parse_simple_blocked_by_cross_repo():
    """Simple blocked_by with cross-repo refs."""
    from beadhub.beads_sync import parse_blocked_by_array

    result = parse_blocked_by_array(["bd-001", "other-repo:bd-002"], "myrepo", "main")
    assert result == [
        {"repo": "myrepo", "branch": "main", "bead_id": "bd-001"},
        {"repo": "other-repo", "branch": "main", "bead_id": "bd-002"},
    ]


def test_parse_simple_blocked_by_invalid_entries():
    """Invalid entries in blocked_by array are skipped."""
    from beadhub.beads_sync import parse_blocked_by_array

    # Mix of valid and invalid
    result = parse_blocked_by_array(["bd-001", "", "../bad", "bd-002"], "myrepo", "main")
    assert result == [
        {"repo": "myrepo", "branch": "main", "bead_id": "bd-001"},
        {"repo": "myrepo", "branch": "main", "bead_id": "bd-002"},
    ]


def test_parse_simple_blocked_by_empty():
    """Empty blocked_by array returns empty list."""
    from beadhub.beads_sync import parse_blocked_by_array

    assert parse_blocked_by_array([], "myrepo", "main") == []
    assert parse_blocked_by_array(None, "myrepo", "main") == []


def test_parse_blocked_by_structured_dicts():
    """Structured dict format should be accepted and preserved."""
    from beadhub.beads_sync import parse_blocked_by_array

    # Structured dicts with repo, branch, bead_id
    input_dicts = [
        {"repo": "my-project", "branch": "main", "bead_id": "bd-auth-001"},
        {"repo": "other-repo", "branch": "feature", "bead_id": "bd-xyz-002"},
    ]
    result = parse_blocked_by_array(input_dicts, "default-repo", "default-branch")

    # Should preserve the structured format exactly
    assert result == [
        {"repo": "my-project", "branch": "main", "bead_id": "bd-auth-001"},
        {"repo": "other-repo", "branch": "feature", "bead_id": "bd-xyz-002"},
    ]


def test_parse_blocked_by_structured_dict_validation():
    """Structured dicts with missing or invalid fields should be rejected."""
    from beadhub.beads_sync import parse_blocked_by_array

    # Missing bead_id - should be skipped
    assert (
        parse_blocked_by_array(
            [{"repo": "my-project", "branch": "main"}], "default-repo", "default-branch"
        )
        == []
    )

    # Invalid bead_id format - should be skipped
    assert (
        parse_blocked_by_array(
            [{"repo": "my-project", "branch": "main", "bead_id": "../bad"}],
            "default-repo",
            "default-branch",
        )
        == []
    )

    # Mix of valid and invalid
    result = parse_blocked_by_array(
        [
            {"repo": "my-project", "branch": "main", "bead_id": "bd-001"},
            {"repo": "bad", "bead_id": "../invalid"},  # invalid bead_id
            {"repo": "other", "branch": "dev", "bead_id": "bd-002"},
        ],
        "default-repo",
        "default-branch",
    )
    assert result == [
        {"repo": "my-project", "branch": "main", "bead_id": "bd-001"},
        {"repo": "other", "branch": "dev", "bead_id": "bd-002"},
    ]


def test_parse_blocked_by_structured_dict_defaults():
    """Structured dicts with missing repo/branch should use defaults."""
    from beadhub.beads_sync import parse_blocked_by_array

    # Missing repo - should use default
    result = parse_blocked_by_array(
        [{"branch": "main", "bead_id": "bd-001"}], "default-repo", "default-branch"
    )
    assert result == [{"repo": "default-repo", "branch": "main", "bead_id": "bd-001"}]

    # Missing branch - should use default
    result = parse_blocked_by_array(
        [{"repo": "my-project", "bead_id": "bd-001"}], "default-repo", "default-branch"
    )
    assert result == [{"repo": "my-project", "branch": "default-branch", "bead_id": "bd-001"}]

    # Missing both repo and branch - should use both defaults
    result = parse_blocked_by_array([{"bead_id": "bd-001"}], "default-repo", "default-branch")
    assert result == [{"repo": "default-repo", "branch": "default-branch", "bead_id": "bd-001"}]


def test_parse_dependency_ref_accepts_valid_repos():
    """Valid repo names should be accepted in cross-repo refs."""
    valid_repos = [
        "my-repo",
        "backend_service",
        "org/project",  # GitHub-style org/repo
        "a",  # Single char
        "ABC-123_test",  # Mixed case and separators
        "a" * 127,  # Max segment length
        f"{'a' * 127}/{'b' * 127}",  # Max total length with org/repo
    ]
    for repo in valid_repos:
        result = _parse_dependency_ref(f"{repo}:bd-123", "myrepo", "main")
        assert result is not None, f"Should accept valid repo: {repo!r}"
        assert result["repo"] == repo


def test_parse_dependency_ref_rejects_malicious_repo():
    """Cross-repo refs with malicious repo names should be rejected."""
    # SQL injection attempts
    assert _parse_dependency_ref("'; DROP TABLE users;--:bd-123", "myrepo", "main") is None
    assert _parse_dependency_ref("repo' OR '1'='1:bd-123", "myrepo", "main") is None

    # Path traversal attempts - including ones that don't start with dots
    assert _parse_dependency_ref("../../../etc:bd-123", "myrepo", "main") is None
    assert _parse_dependency_ref("..\\..\\windows:bd-123", "myrepo", "main") is None
    assert _parse_dependency_ref("a/../../../etc:bd-123", "myrepo", "main") is None
    assert _parse_dependency_ref("repo/../evil:bd-123", "myrepo", "main") is None
    assert _parse_dependency_ref("a/./b:bd-123", "myrepo", "main") is None

    # Shell injection attempts
    assert _parse_dependency_ref("$(whoami):bd-123", "myrepo", "main") is None
    assert _parse_dependency_ref("`rm -rf /`:bd-123", "myrepo", "main") is None

    # Control characters
    assert _parse_dependency_ref("repo\x00evil:bd-123", "myrepo", "main") is None
    assert _parse_dependency_ref("repo\ninjection:bd-123", "myrepo", "main") is None


def test_parse_blocked_by_structured_rejects_malicious_repo():
    """Structured dicts with malicious repo names should be rejected."""
    from beadhub.beads_sync import parse_blocked_by_array

    malicious_repos = [
        "'; DROP TABLE users;--",
        "../../../etc/passwd",
        "a/../../../etc/passwd",  # Path traversal not starting with dots
        "repo/../evil",
        "a/./b",  # Current directory reference
        "$(whoami)",
        "`rm -rf /`",
        "repo\x00evil",
        "repo\ninjected",
    ]

    for malicious in malicious_repos:
        result = parse_blocked_by_array(
            [{"repo": malicious, "branch": "main", "bead_id": "bd-123"}],
            "default-repo",
            "default-branch",
        )
        assert result == [], f"Should reject malicious repo: {malicious!r}"


def test_parse_blocked_by_structured_rejects_malicious_branch():
    """Structured dicts with malicious branch names should be rejected."""
    from beadhub.beads_sync import parse_blocked_by_array

    malicious_branches = [
        "'; DROP TABLE users;--",
        "../../../etc/passwd",
        "$(whoami)",
        "branch\x00evil",
        "branch\ninjected",
    ]

    for malicious in malicious_branches:
        result = parse_blocked_by_array(
            [{"repo": "valid-repo", "branch": malicious, "bead_id": "bd-123"}],
            "default-repo",
            "default-branch",
        )
        assert result == [], f"Should reject malicious branch: {malicious!r}"
