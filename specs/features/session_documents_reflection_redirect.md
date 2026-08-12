# Phase 2: Reflection Redirect to Session Documents

> **Status: PLANNED — not yet implemented.** This spec documents the follow-on work
> after v1 of session documents ships. The schema hooks (`reflections.target_type`
> and `reflections.document_id`) are already in place from the v1 migration.

## Context

In v1, session documents were introduced as a new aggregation layer (`/build_doc` →
`SessionBuilderService.build()`). Each document is a single markdown text stored in
`session_documents.content` with a fixed skeleton:

```markdown
# {title}

## Summary
## Key Ideas
## Open Questions
## Knowledge Gaps
## Reflections
## Mind Changes
```

The LLM fills **Summary** + **Key Ideas** at build time. The other 4 sections are
empty placeholders. Reflection still targets individual notes: `NoteSelectorService`
picks one note, sub-agents operate on a single note, and `reflections.voice_note_id`
is the link.

The user's goal is to review **session documents**, not individual notes, because
documents provide enough context to test real understanding (not just memorization).

## Scope

### In Scope
- `SessionSelectorService` — sibling to `NoteSelectorService`. Picks a non-internalized
  `session_documents` row from the active source.
- Document-flavored prompts for `QuestionAgent`, `ScorerAgent`, `HintAgent` — input is
  the document's full `content` markdown (not a single note).
- `MultiAgentService._reflect_node` updated to call `SessionSelectorService` and create
  `reflections` rows with `target_type='document'` and `document_id` populated.
- **Document evolution**: when a gap, open question, reflection, or mind change emerges
  during Socratic review, the agent **appends content under the appropriate section header**
  in `session_documents.content` and writes it back via `update_content()`. The document
  is one portable markdown file that evolves over time.
- `/reflect stats` rewritten to count over `session_documents` instead of `voice_notes`.
- `session_documents.status` transitions to `'reviewed'` when internalization criteria
  are met.
- `reflections.voice_note_id` becomes optional for document-targeted reflections.

### Out of Scope
- Source-level synthesis (`parent_document_id` populated) — Phase 3.
- Web UI for viewing documents — separate frontend spec.
- Multi-user support — still single-user.
- Export to S3/Notion — future infrastructure work.

## Design

### SessionSelectorService

```python
class SessionSelectorService:
    """Selects a non-internalized session document from a source."""

    def __init__(
        self,
        session_documents_repository: SessionDocumentsRepository,
        reflection_repository: ReflectionRepository,
    ) -> None: ...

    async def pick_document(self, source_id: str) -> Optional[dict]:
        """
        1. Fetch session_documents for source_id where status='ready'
        2. Get reflection stats for those documents (completed reflections only)
        3. Filter out internalized documents
        4. Return random.choice(eligible) or None
        """
```

### Document-flavored prompts

The sub-agents (`QuestionAgent`, `ScorerAgent`, `HintAgent`) get new prompt templates
that take the document's full `content` markdown instead of a single note's `raw_text`.
The existing note-flavored prompts stay for backward compatibility.

### Document evolution (the key mechanism)

When a Socratic review interaction produces a new insight:

```python
async def append_to_section(document_id: str, section: str, content: str) -> None:
    """
    1. Fetch the current document content
    2. Find the section header (## {section})
    3. Append the new content below the section, before the next ## header
    4. Write back via update_content()
    """
```

Sections that Phase 2 can append to:
- `## Open Questions` — questions the user couldn't answer or found interesting
- `## Knowledge Gaps` — areas where understanding was incomplete
- `## Reflections` — new insights or connections discovered during review
- `## Mind Changes` — cases where the user revised their thinking

### MultiAgentService changes

`_start_reflection` in `MultiAgentService` calls `SessionSelectorService.pick_document()`
instead of `NoteSelectorService.pick_note()`. The `ReflectionContext` in `AgentState`
gains `document_id` and `document_content` fields. `reflections` rows are created with
`target_type='document'` and `document_id` populated.

### /reflect stats rewrite

`ReflectionService.get_reflection_summary()` is rewritten to count over
`session_documents` instead of `voice_notes`. The `get_reflection_summary` RPC function
in Supabase is updated to join `session_documents` instead of `voice_notes`.

## File Changes (planned)

```
backend/
  services/
    session_selector_service.py                    ← new
    agents/question_agent.py                       ← modified: document prompt
    agents/scorer_agent.py                         ← modified: document prompt
    agents/hint_agent.py                           ← modified: document prompt
    multi_agent_service.py                         ← modified: _start_reflection uses SessionSelectorService
    reflection_service.py                          ← modified: get_reflection_summary counts documents
    session_builder_service.py                     ← modified: add append_to_section helper
  repositories/
    session_documents_repository.py                ← modified: add get_reflection_stats
  models/
    agent.py                                       ← modified: ReflectionContext gains document fields
  controllers/
    telegram_controller.py                         ← modified: wire SessionSelectorService

docs/sql/
  reflection_redirect_migration.md                 ← new: update get_reflection_summary RPC

tests/
  services/test_session_selector_service.py        ← new
  test_multi_agent_service.py                      ← extended: document-targeted reflection
```

## Acceptance Criteria (planned)

- [ ] `/reflect` picks a session document (not a note) from the active source
- [ ] Question is generated from the document's full `content` markdown
- [ ] `reflections` row created with `target_type='document'` and `document_id` populated
- [ ] After a reflection, new content is appended under the appropriate section header
- [ ] `/reflect stats` shows counts over `session_documents`
- [ ] `session_documents.status` transitions to `'reviewed'` when internalization criteria met
- [ ] No regression in chat mode or note mode
- [ ] Full test suite passes

## Dependencies

- v1 of session documents must be shipped and stable
- `reflections.target_type` and `reflections.document_id` columns (already applied in v1 migration)
