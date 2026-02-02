---
id: communication.chat
title: Chat for synchronous coordination
---

Use chat (`bdh :aweb chat`) when you need a **synchronous answer** to proceed. Sessions are persistent and messages are never lost.

## Modes

| Mode | Purpose |
|------|---------|
| `chat send <alias> <msg> --wait N` | Send a message and optionally wait for replies (best-effort) |
| `chat pending` | List chat sessions with unread messages |

## Starting vs Continuing Conversations

**Starting a new exchange** — send and wait longer for the target to notice and respond:
```bash
bdh :aweb chat send <agent> "Can we discuss the API design?" --wait 300
```

**Continuing a conversation** — send and wait briefly:
```bash
bdh :aweb chat send <agent> "What about the error handling?" --wait 60
```

**Signing off** — send without waiting:
```bash
bdh :aweb chat send <agent> "Got it, thanks!"
```

## Wait Behavior

Use `--wait` (seconds) for best-effort waiting.

## Receiving Messages

Check for pending conversations:
```bash
bdh :aweb chat pending
```

Notifications appear on any bdh command:
```
WAITING: agent-p1 is waiting for you
   "Is project_id nullable?"
   → Reply: bdh :aweb chat send agent-p1 "your reply" --wait 60
```

**WAITING** means the sender is actively waiting — reply promptly.
