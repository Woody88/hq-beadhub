# BeadHub Workspace

> Always use `bdh` (not `bd`) — it coordinates work across agents.

**Start every session:**
```bash
bdh :status    # your identity
bdh :policy    # READ AND FOLLOW
bdh ready      # find work
```

**Before ending session:**
```bash
git status && git add <files>
bdh sync --from-main
git commit -m "..."
```
