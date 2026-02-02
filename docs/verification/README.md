# BeadHub Quickstart Verification

Instructions for an agent to verify the README quickstart works correctly.

## Prerequisites

- `bdh` in PATH
- `bd` (Beads) in PATH (https://github.com/steveyegge/beads)
- BeadHub running at `http://localhost:9000`
- Playwright MCP for screenshots

## Steps

### 1. Clean up and create demo repo

```bash
rm -rf /tmp/demo-repo /tmp/demo-repo-alice
mkdir -p /tmp/demo-repo
cd /tmp/demo-repo
git init
git remote add origin https://github.com/example/demo.git
```

### 2. Initialize BeadHub workspace

```bash
export BEADHUB_URL=http://localhost:9000
bdh :init --project demo --alias dev-01 --human 'Demo User' --role developer
```

### 3. Create sample beads

```bash
bdh create 'Fix login bug' -t bug -p 2
bdh create 'Add dark mode' -t feature -p 3
```

Note the bead IDs (e.g., `demo-repo-eag`, `demo-repo-a83`).

### 4. Verify ready work and status

```bash
bdh ready
bdh :aweb whoami
```

### 5. Take dashboard screenshots (900x600, dark mode)

Navigate to `http://localhost:9000`, enable dark mode (toggle in header), filter to "demo" project:
- Status page → `docs/images/demo-status.png`
- Beads page → `docs/images/demo-beads.png`
- Workspaces page → `docs/images/demo-workspaces.png`

### 6. Create second agent

```bash
cd /tmp/demo-repo
git worktree add /tmp/demo-repo-alice -b alice
cd /tmp/demo-repo-alice
bdh :init --project demo --alias alice --human 'Alice' --role backend
```

### 7. Claim work and test collision

dev-01 claims the bug:
```bash
cd /tmp/demo-repo
bdh update <BEAD_ID> --status in_progress
```

alice tries same bead (should be rejected):
```bash
cd /tmp/demo-repo-alice
bdh update <BEAD_ID> --status in_progress
```

### 8. Test messaging

Use **chat** for quick coordination (e.g., asking to take a claimed bead):

```bash
cd /tmp/demo-repo-alice
bdh :aweb chat send dev-01 'Can I take the login bug?' --wait 10

cd /tmp/demo-repo
bdh :aweb chat send alice "Yes — go for it."
```

Use **mail** for async handoffs when work is done:

```bash
cd /tmp/demo-repo-alice
bdh :aweb mail send dev-01 'Done with the login bug. Summary: … Tests: … Next: …'

cd /tmp/demo-repo
bdh :aweb mail list
```

### 9. Take multi-agent screenshots (dark mode)

- Workspaces (2 online) → `docs/images/demo-workspaces-2.png`
- Claims page → `docs/images/demo-claims.png`

### 10. Clean up

```bash
rm -rf /tmp/demo-repo /tmp/demo-repo-alice
```

## Expected Output

See `quickstart-output.txt` for captured command output from a verification run.
