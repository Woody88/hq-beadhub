#!/usr/bin/env bash
set -euo pipefail

# message-watcher.sh — Ordis control-plane message loop
#
# Polls BeadHub for pending chat messages via HTTP API,
# generates responses with claude -p (text only, no tool use),
# and sends responses back via the API.
#
# Required env vars:
#   BEADHUB_API              — BeadHub API base URL (e.g., http://beadhub-api)
#   ORDIS_API_KEY            — Ordis's aweb API key (aw_sk_...)
#   DISCORD_ORDIS_WEBHOOK_URL — Discord webhook for #ordis channel
#   CLAUDE_CODE_OAUTH_TOKEN  — Claude Code auth token (from claude setup-token)
#
# Optional:
#   POLL_INTERVAL — seconds between polls (default: 5)

POLL_INTERVAL="${POLL_INTERVAL:-5}"

echo "[message-watcher] Entering message watch loop (poll every ${POLL_INTERVAL}s)..."

# Message handling: bash does ALL chat I/O via HTTP API, claude -p only generates text
while true; do
  # Get pending sessions via BeadHub API (Bearer auth)
  pending_json=$(curl -sf -H "Authorization: Bearer $ORDIS_API_KEY" \
    "$BEADHUB_API/v1/chat/pending" 2>/dev/null || echo "")

  # Filter to sessions where last message is NOT from ordis (skip self)
  actionable=$(echo "$pending_json" | jq -r '[.pending[] | select(.last_from != "ordis")] | length' 2>/dev/null || echo "0")
  if [ "$actionable" -gt 0 ]; then
    echo "[message-watcher] $actionable actionable message(s) detected"

    for session_id in $(echo "$pending_json" | jq -r '.pending[] | select(.last_from != "ordis") | .session_id'); do
      if [ -z "$session_id" ]; then continue; fi
      # Get who sent the message
      sender=$(echo "$pending_json" | jq -r ".pending[] | select(.session_id==\"$session_id\") | .last_from // \"someone\"")

      # Read messages from this session via admin API
      msg_json=$(curl -sf -H "Authorization: Bearer $ORDIS_API_KEY" \
        "$BEADHUB_API/v1/chat/admin/sessions/$session_id/messages?limit=5" 2>/dev/null || echo "")

      if [ -z "$msg_json" ]; then
        echo "[message-watcher] Warning: could not read messages from session $session_id"
        continue
      fi

      # Extract the latest unread messages (from sender, not from ordis)
      messages=$(echo "$msg_json" | jq -r '.messages[] | select(.from_agent != "ordis") | "\(.from_agent): \(.body)"' 2>/dev/null | tail -5)
      if [ -z "$messages" ]; then continue; fi

      echo "[message-watcher] Processing messages from $sender"

      # Generate response via claude -p (text only, no tool use)
      response=$(claude -p "You are ordis, a helpful AI coordinator. A user messaged you via Discord. Their message:

$messages

Reply concisely and helpfully. Do NOT use any tools or run commands — just reply with text." 2>&1 || echo "Sorry, I had trouble processing that. Could you try again?")

      # Send response back via API (POST to session)
      if [ -n "$response" ]; then
        escaped_response=$(echo "$response" | jq -Rs .)
        curl -sf -X POST -H "Authorization: Bearer $ORDIS_API_KEY" \
          -H "Content-Type: application/json" \
          -d "{\"body\": $escaped_response}" \
          "$BEADHUB_API/v1/chat/sessions/$session_id/messages" 2>/dev/null || \
          echo "[message-watcher] Warning: failed to send response to session $session_id"
        echo "[message-watcher] Response sent to $sender"
      fi
    done
  fi
  sleep "$POLL_INTERVAL"
done
