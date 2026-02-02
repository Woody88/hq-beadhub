---
name: release
description: Create a new bdh release. Pushes main to origin and creates a release tag that triggers the binary build workflow.
---

# Release Skill

Creates a new bdh release by pushing code and creating a release tag.

## What This Does

1. Verifies main branch is clean and ready
2. Pushes main to origin
3. Creates a semver tag (e.g., `v0.1.0`)
4. Pushes the tag to trigger the release workflow

The `bdh-release.yml` GitHub Action will then:
- Build binaries for linux/darwin/windows × amd64/arm64
- Create a GitHub Release with checksums
- Make the curl installer work: `curl -fsSL https://raw.githubusercontent.com/beadhub/bdh/main/install.sh | sh`

## Instructions

1. First, check the current state:
   ```bash
   cd /Users/juanre/prj/beadhub-all/bdh
   git status
   git log origin/main..HEAD --oneline
   ```

2. Show the user what will be pushed and ask for the version number.

3. If user confirms, execute the release:
   ```bash
   cd /Users/juanre/prj/beadhub-all/bdh
   git push origin main
   git tag v<VERSION>
   git push origin v<VERSION>
   ```

4. Provide the URL to watch the release workflow:
   `https://github.com/beadhub/bdh/actions`

## Version Format

Tags must follow: `v<MAJOR>.<MINOR>.<PATCH>`

Examples:
- `v0.1.0` - Initial release
- `v0.1.1` - Patch release
- `v0.2.0` - Minor release with new features

## Pre-release Checklist

Before releasing, verify:
- [ ] All tests pass locally
- [ ] CI is green (or will be after push)
- [ ] README install URL points to `beadhub/bdh`
- [ ] No uncommitted changes on main

## After Release

The release workflow takes ~2-3 minutes. Once complete:
- Binaries available at: `https://github.com/beadhub/bdh/releases`
- Curl installer will download prebuilt binaries instead of building from source
