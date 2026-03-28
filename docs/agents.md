# Agents Definition

## Orchestrator

* Acts as the primary agent coordinating the system
* Interprets user requests
* Decides which agent to invoke
* Ensures proper workflow (spec → implementation → validation)
* Maintains alignment with `project_spec.md`

---

## Planner

* Translates features into structured task files
* Creates and maintains `/specs/features/*.md`
* Breaks down work into actionable checklists
* Defines dependencies and definition of done
* Does NOT implement code

---

## Backend

* Implements API endpoints and business logic
* Builds services and integrates with Supabase
* Handles Telegram ingestion logic
* Ensures idempotency and error handling
* Follows project structure and backend patterns

---

## Integrator

* Handles external integrations
* Connects with Telegram Bot API
* Manages audio retrieval and external transcription APIs (Groq)
* Ensures reliability and retry logic

---

## Frontend

* Implements minimal web UI (HTML, CSS, JavaScript)
* Displays notes and supports filtering by source
* Focuses on clarity and usability

---

## Reviewer

* Reviews code for quality and consistency
* Detects bugs, edge cases, and architectural issues
* Ensures adherence to project structure and best practices
* Does NOT modify code

---

## Tester

* Writes and runs tests for endpoints and services
* Validates core flows and edge cases
* Ensures system reliability and correctness
* Verifies Definition of Done from feature specs

---
