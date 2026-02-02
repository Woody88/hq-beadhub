# Changelog

All notable changes to this project are documented in this file.

This project follows a pragmatic, OSS-friendly changelog format (similar to Keep a Changelog), but versioning is currently evolving.

## Unreleased

## 0.1.0 — 2026-01-06

Initial open-source release.

### Added
- FastAPI server with Redis + Postgres backing services
- Real-time dashboard (SSE) for status, workspaces, claims, escalations, issues, and policies
- Beads integration (client-push sync of `.beads/issues.jsonl`)
- Agent messaging + chat sessions
- `bdh` CLI wrapper for bead-level coordination (preflight approve/reject + sync)

### Security
- Project-scoped tenant isolation model (`project_id`)
- CLI safety checks for repo identity / destructive actions

