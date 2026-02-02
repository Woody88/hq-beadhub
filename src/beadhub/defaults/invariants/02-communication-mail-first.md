---
id: communication.mail-first
title: Mail-first communication
---

Default to mail (`bdh :aweb mail`) for coordination.

Use mail for:
- Status updates and progress reports
- Review requests and feedback
- FYI notifications
- Non-blocking questions

## Sending Messages

```bash
bdh :aweb mail send <agent> "Status update: completed bd-42"
bdh :aweb mail send <agent> "Review request: PR #123 ready" --subject "Review needed"
```

## Checking Your Inbox

```bash
bdh :aweb mail list           # Show unread messages
bdh :aweb mail list --all     # Include read messages
```

## Reading Messages

```bash
bdh :aweb mail open <sender>   # Read unread mail from sender (acknowledges)
```

Use chat (`bdh :aweb chat`) only when you need a synchronous answer to proceed. See the **communication.chat** invariant for chat details.

**Respond immediately to WAITING notifications** — someone is blocked waiting for your reply.
