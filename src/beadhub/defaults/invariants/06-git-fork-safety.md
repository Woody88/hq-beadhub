---
id: git.fork-safety
title: Git fork and PR safety
---

## Fork Safety

All repos under this organization are forks. If you don't set the default remote, `gh pr create` will target the **upstream public repo** — leaking code and creating PRs where they don't belong.

**After cloning any repo, ALWAYS run:**
```bash
gh repo set-default OWNER/REPO
```

This ensures `gh pr create` targets the correct fork, not the upstream.

## PR Rules

- NEVER create PRs on repos you don't own
- ALWAYS verify the target repo before running `gh pr create`:
  ```bash
  gh repo set-default --view   # Confirm the default repo
  ```
- If a repo was cloned from a fork, the `origin` remote may point to the upstream — check with `git remote -v`
- When in doubt, use `gh pr create --repo OWNER/REPO` to be explicit
