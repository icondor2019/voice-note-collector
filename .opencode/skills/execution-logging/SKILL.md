---
name: execution-logging
description: Provide a single, chronological, append-only log of all agent actions within a feature spec.
---

## Location

All logs must be written inside the feature file under:

## Execution Log

---

## Rules

- Logs are APPEND-ONLY (never overwrite or delete previous entries)
- All agents write to the SAME log (no per-agent sections)
- Each entry MUST include agent name
- Entries must be chronological (newest at the bottom)
- Keep messages concise and factual

---

## Format

Each log entry must follow this structure:

- [YYYY-MM-DD HH:MM] Agent: <AgentName> | Status: <pending | in_progress | completed | failed> | <short message>

---

## Example

## Execution Log

- [2026-03-28 14:00] Agent: Planner | Status: completed | Defined feature and tasks
- [2026-03-28 14:10] Agent: Architect | Status: completed | Proposed structure and interfaces
- [2026-03-28 14:30] Agent: Backend | Status: in_progress | Started implementation
- [2026-03-28 14:50] Agent: Backend | Status: completed | Controllers implemented
- [2026-03-28 15:10] Agent: Reviewer | Status: pending | Awaiting validation

---

## Status Definitions

- pending → not started or waiting for input
- in_progress → currently working
- completed → task finished successfully
- failed → blocked or error occurred

---

## When to Log

- When starting work → log in_progress
- When finishing → log completed
- When blocked/error → log failed
- When waiting on another agent/user → log pending

---

## Constraints

- Do NOT overwrite previous entries
- Do NOT change format
- Do NOT remove logs
- Do NOT create separate sections per agent

---

## Key Principle

The LAST log entry represents the current state of the feature.