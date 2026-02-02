"""Tests for default policy bundle loading from markdown files."""

import pytest

from beadhub.defaults import (
    load_default_bundle,
    load_invariant,
    load_role,
    parse_frontmatter,
)


class TestParseFrontmatter:
    """Tests for YAML frontmatter parsing."""

    def test_parse_frontmatter_basic(self):
        """Parse basic frontmatter with body."""
        content = """---
id: test.invariant
title: Test Invariant
---

This is the body content.
"""
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter["id"] == "test.invariant"
        assert frontmatter["title"] == "Test Invariant"
        assert body.strip() == "This is the body content."

    def test_parse_frontmatter_multiline_body(self):
        """Parse frontmatter with multiline body."""
        content = """---
id: multi
title: Multi
---

Line one.

Line two.

Line three.
"""
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter["id"] == "multi"
        assert "Line one." in body
        assert "Line two." in body
        assert "Line three." in body

    def test_parse_frontmatter_no_body(self):
        """Parse frontmatter with empty body."""
        content = """---
id: empty
title: Empty
---
"""
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter["id"] == "empty"
        assert body.strip() == ""

    def test_parse_frontmatter_missing_raises(self):
        """Raise error when frontmatter is missing."""
        content = "Just body content without frontmatter."
        with pytest.raises(ValueError, match="missing.*frontmatter"):
            parse_frontmatter(content)

    def test_parse_frontmatter_malformed_raises(self):
        """Raise error when frontmatter is malformed."""
        content = """---
id: test
title
---
body
"""
        with pytest.raises(ValueError, match="invalid.*frontmatter"):
            parse_frontmatter(content)


class TestLoadInvariant:
    """Tests for loading invariant from markdown file."""

    def test_load_invariant_basic(self, tmp_path):
        """Load a basic invariant file."""
        invariant_file = tmp_path / "test-invariant.md"
        invariant_file.write_text(
            """---
id: tracking.bdh-only
title: Use bdh for tracking
---

Track all tasks and issues in BeadHub (`bdh`).

Do not create markdown TODO lists.
"""
        )
        invariant = load_invariant(invariant_file)
        assert invariant["id"] == "tracking.bdh-only"
        assert invariant["title"] == "Use bdh for tracking"
        assert "BeadHub" in invariant["body_md"]
        assert "TODO" in invariant["body_md"]

    def test_load_invariant_missing_id_raises(self, tmp_path):
        """Raise error when id is missing."""
        invariant_file = tmp_path / "no-id.md"
        invariant_file.write_text(
            """---
title: No ID
---
Body.
"""
        )
        with pytest.raises(ValueError, match="missing.*id"):
            load_invariant(invariant_file)

    def test_load_invariant_missing_title_raises(self, tmp_path):
        """Raise error when title is missing."""
        invariant_file = tmp_path / "no-title.md"
        invariant_file.write_text(
            """---
id: no.title
---
Body.
"""
        )
        with pytest.raises(ValueError, match="missing.*title"):
            load_invariant(invariant_file)


class TestLoadRole:
    """Tests for loading role from markdown file."""

    def test_load_role_basic(self, tmp_path):
        """Load a basic role file."""
        role_file = tmp_path / "coordinator.md"
        role_file.write_text(
            """---
id: coordinator
title: Coordinator
---

## Coordinator Role

You own the overall project outcome.

Your responsibilities:
- Keep the final goal explicit
- Break epics into beads
"""
        )
        role_id, role_data = load_role(role_file)
        assert role_id == "coordinator"
        assert role_data["title"] == "Coordinator"
        assert "project outcome" in role_data["playbook_md"]
        assert "responsibilities" in role_data["playbook_md"]

    def test_load_role_missing_id_raises(self, tmp_path):
        """Raise error when id is missing."""
        role_file = tmp_path / "no-id.md"
        role_file.write_text(
            """---
title: No ID
---
Playbook.
"""
        )
        with pytest.raises(ValueError, match="missing.*id"):
            load_role(role_file)

    def test_load_role_missing_title_raises(self, tmp_path):
        """Raise error when title is missing."""
        role_file = tmp_path / "no-title.md"
        role_file.write_text(
            """---
id: no_title
---
Playbook.
"""
        )
        with pytest.raises(ValueError, match="missing.*title"):
            load_role(role_file)


class TestLoadDefaultBundle:
    """Tests for loading the complete default policy bundle."""

    def test_load_default_bundle(self, tmp_path):
        """Load a complete bundle from directory structure."""
        # Create directory structure
        invariants_dir = tmp_path / "invariants"
        roles_dir = tmp_path / "roles"
        invariants_dir.mkdir()
        roles_dir.mkdir()

        # Create invariant files
        (invariants_dir / "tracking.md").write_text(
            """---
id: tracking.bdh-only
title: Use bdh for tracking
---
Track tasks in bdh.
"""
        )
        (invariants_dir / "communication.md").write_text(
            """---
id: communication.mail-first
title: Mail-first communication
---
Use mail for coordination.
"""
        )

        # Create role files
        (roles_dir / "coordinator.md").write_text(
            """---
id: coordinator
title: Coordinator
---
## Coordinator
Own the project outcome.
"""
        )
        (roles_dir / "implementer.md").write_text(
            """---
id: implementer
title: Implementer
---
## Implementer
Write code and tests.
"""
        )

        bundle = load_default_bundle(tmp_path)

        # Check invariants
        assert len(bundle["invariants"]) == 2
        invariant_ids = {inv["id"] for inv in bundle["invariants"]}
        assert "tracking.bdh-only" in invariant_ids
        assert "communication.mail-first" in invariant_ids

        # Check roles
        assert len(bundle["roles"]) == 2
        assert "coordinator" in bundle["roles"]
        assert "implementer" in bundle["roles"]
        assert bundle["roles"]["coordinator"]["title"] == "Coordinator"

        # Check adapters (empty by default)
        assert bundle["adapters"] == {}

    def test_load_default_bundle_ignores_non_md_files(self, tmp_path):
        """Ignore non-markdown files in directories."""
        invariants_dir = tmp_path / "invariants"
        roles_dir = tmp_path / "roles"
        invariants_dir.mkdir()
        roles_dir.mkdir()

        # Create valid invariant
        (invariants_dir / "valid.md").write_text(
            """---
id: valid
title: Valid
---
Valid invariant.
"""
        )
        # Create non-md file that should be ignored
        (invariants_dir / "README.txt").write_text("This should be ignored")
        (invariants_dir / ".hidden.md").write_text("Hidden files ignored too")

        # Create valid role
        (roles_dir / "tester.md").write_text(
            """---
id: tester
title: Tester
---
Test role.
"""
        )

        bundle = load_default_bundle(tmp_path)
        assert len(bundle["invariants"]) == 1
        assert bundle["invariants"][0]["id"] == "valid"

    def test_load_default_bundle_empty_dirs(self, tmp_path):
        """Handle empty directories gracefully."""
        invariants_dir = tmp_path / "invariants"
        roles_dir = tmp_path / "roles"
        invariants_dir.mkdir()
        roles_dir.mkdir()

        bundle = load_default_bundle(tmp_path)
        assert bundle["invariants"] == []
        assert bundle["roles"] == {}
        assert bundle["adapters"] == {}

    def test_load_default_bundle_missing_dirs_raises(self, tmp_path):
        """Raise error when required directories are missing."""
        # Only create invariants dir
        (tmp_path / "invariants").mkdir()

        with pytest.raises(ValueError, match="missing.*roles"):
            load_default_bundle(tmp_path)


class TestDefaultBundleIntegration:
    """Integration tests using the actual default files."""

    def test_load_actual_defaults(self):
        """Load the actual default bundle from the package."""
        from beadhub.defaults import get_default_bundle

        bundle = get_default_bundle()

        # Should have invariants
        assert len(bundle["invariants"]) >= 5
        invariant_ids = {inv["id"] for inv in bundle["invariants"]}
        assert "tracking.bdh-only" in invariant_ids
        assert "communication.mail-first" in invariant_ids

        # Should have roles
        assert "coordinator" in bundle["roles"]
        assert "implementer" in bundle["roles"]
        assert "reviewer" in bundle["roles"]

        # Each role should have title and playbook_md
        for role_id, role_data in bundle["roles"].items():
            assert "title" in role_data, f"Role {role_id} missing title"
            assert "playbook_md" in role_data, f"Role {role_id} missing playbook_md"

        # Each invariant should have id, title, body_md
        for inv in bundle["invariants"]:
            assert "id" in inv
            assert "title" in inv
            assert "body_md" in inv

    def test_get_default_bundle_returns_copies(self):
        """Verify get_default_bundle returns copies to prevent mutation."""
        from beadhub.defaults import get_default_bundle

        bundle1 = get_default_bundle()
        bundle2 = get_default_bundle()

        # Should be different objects (copies)
        assert bundle1 is not bundle2
        # But with equal content
        assert bundle1 == bundle2

    def test_get_default_bundle_mutation_safe(self):
        """Verify mutations don't affect cached bundle."""
        from beadhub.defaults import clear_default_bundle_cache, get_default_bundle

        clear_default_bundle_cache()
        bundle1 = get_default_bundle()
        original_count = len(bundle1["invariants"])

        # Mutate the returned bundle
        bundle1["invariants"].append({"id": "evil", "title": "Evil", "body_md": "Bad"})

        # Get another copy - should not see the mutation
        bundle2 = get_default_bundle()
        assert len(bundle2["invariants"]) == original_count
