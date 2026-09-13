## 1. Feature: dashboard_recording_metrics

### 2. Context

The authenticated, read-only web dashboard currently presents four editorial metric cards: notes, documents, sources, and last capture. The user wants to refine this existing visual language and add two globally scoped recording metrics without changing the dashboard into a different product or interaction model.

The confirmed definitions are:

- Total recording time is the sum of `voice_notes.duration_seconds` across every note, including notes from active and archived sources. Null durations are ignored and an empty result is treated as zero.
- Pending notes are notes whose related `voice_note_details.status` is exactly `created`.
- Recording time is displayed in a compact human-readable form such as `12 h 34 min`.
- The pending metric links to `/notes?status=created`.
- The existing quiet editorial aesthetic must be preserved and refined, including responsive and accessible behavior.

Graphify preflight used `/Users/ivancondor/repositories/voice-note-collector/graphify-out/graph.json`. Its initial breadth-first result surfaced `VoiceNotesRepository` and related services but did not identify the dashboard precisely. A targeted review established the current path as `backend/controllers/web_controller.py` → `backend/services/dashboard_service.py` → repositories, rendered by `frontend/templates/dashboard/index.html` and styled by `frontend/static/css/app.css`. Existing coverage is concentrated in `tests/services/test_web_library_services.py`, `tests/repositories/test_web_library_queries.py`, and `tests/controllers/test_web_controller.py`.

---

### 3. Spec

### 3.1 Requirements

1. The dashboard summary must include the global sum of all non-null `duration_seconds` values.
2. The dashboard summary must include the global count of notes whose detail status is `created`.
3. Missing durations, an empty database, or an absent aggregate value must produce a zero recording duration rather than an error.
4. Total duration must be presented as whole hours and minutes using the format `<hours> h <minutes> min`; durations below one hour must still have an unambiguous readable representation.
5. The pending count card must navigate to the existing filtered notes library at `/notes?status=created`.
6. Existing dashboard metrics and their behavior must remain available.
7. The dashboard layout must preserve its current editorial identity while improving hierarchy and accommodating six metrics cleanly on desktop, tablet, and mobile.
8. Metric links must retain visible hover and keyboard-focus affordances, and the statistics section must remain meaningfully labeled for assistive technology.
9. No database schema migration, write operation, external dependency, or change to the read-only web model is permitted.
10. All implementation and documentation changes for this feature must remain on branch `codex/dashboard-recording-metrics`.

### 3.2 Acceptance Criteria

- Given durations of 43,200 and 2,040 seconds plus a null duration, the dashboard displays `12 h 34 min`.
- Given no notes or only null durations, the dashboard displays a zero-duration state without failing.
- Given note details with statuses `created`, `enriched`, and `reviewed`, only `created` rows contribute to the pending count.
- The pending metric's link is exactly `/notes?status=created`, and the destination uses the existing note-status filter.
- Notes, documents, sources, and last-capture metrics continue to render with their prior values and semantics.
- Six metric cards form a deliberate, balanced layout at desktop widths and collapse without overflow or illegible content at the existing tablet and mobile breakpoints.
- Linked metric cards are usable with pointer and keyboard input and expose visible focus styling.
- Repository, service, and controller-rendering tests cover the new values and relevant zero/null edge cases.

---

### 4. Design

### 4.1 Architecture

Keep the existing server-rendered flow and dependency boundaries:

1. Extend `VoiceNotesRepository` with a dashboard-specific read method that retrieves the fields needed to calculate global duration and pending status, using the `voice_note_details` relation and existing repository error handling.
2. Return raw numeric statistics from the repository, with null durations excluded from the sum and only `status == "created"` included in the pending count.
3. Extend `DashboardService.get_summary()` to combine these statistics with the existing source, note, document, and last-capture values. Keep human-readable duration formatting in this presentation-oriented service so the template receives a display-ready value while tests can exercise deterministic formatting.
4. Preserve `web_controller.dashboard()` as the delivery boundary; it should continue passing one `summary` object to the template.
5. Add two semantically clear cards to the current metric grid. Refine spacing, type scale, and responsive grid behavior in the existing stylesheet rather than introducing a parallel design system or JavaScript dependency.

### 4.2 File Structure

- `backend/repositories/voice_notes_repository.py`: add the dashboard recording-statistics query/aggregation method.
- `backend/services/dashboard_service.py`: add duration formatting and expose total recording time plus pending-note count in the summary.
- `frontend/templates/dashboard/index.html`: render recording-time and linked pending-note cards while retaining existing metrics.
- `frontend/static/css/app.css`: refine the six-card metric layout and responsive/readability states within the incumbent visual system.
- `tests/repositories/test_web_library_queries.py`: verify duration and pending-status aggregation, including null/empty cases.
- `tests/services/test_web_library_services.py`: verify summary composition and readable duration formatting.
- `tests/controllers/test_web_controller.py`: verify both new metrics and the pending-filter link are rendered.

---

### 5. Tasks

#### Data and service layer

- [x] Add a dashboard recording-statistics method to `VoiceNotesRepository` that returns total duration seconds and the count of related details with status `created`.
- [x] Ensure the repository method treats empty responses and null `duration_seconds` values as zero while preserving existing Supabase error handling.
- [x] Add a deterministic duration formatter in `backend/services/dashboard_service.py` for whole-hour and whole-minute display.
- [x] Extend `DashboardService.get_summary()` with the recording-duration display value and pending-note count without changing existing summary keys.

#### Dashboard interface

- [x] Add the total-recording-time card to `frontend/templates/dashboard/index.html` with concise explanatory copy.
- [x] Add the pending-notes card to `frontend/templates/dashboard/index.html` and link it to `/notes?status=created`.
- [x] Refine the metric grid and card typography in `frontend/static/css/app.css` for a balanced six-card editorial composition.
- [x] Verify linked cards preserve hover and `:focus-visible` feedback and the grid remains readable at existing tablet and mobile breakpoints.

#### Verification

- [x] Add repository tests for mixed durations/statuses, null durations, and an empty result set.
- [x] Add service tests for summary composition and duration formatting at zero, below one hour, exact-hour, and hours-plus-minutes boundaries.
- [x] Update controller/template tests to assert the recording-time copy/value, pending count, and exact filtered-notes URL.
- [x] Run the focused repository, service, and controller web test modules on branch `codex/dashboard-recording-metrics`.

---

### 6. Tests

- [x] Repository aggregation sums valid numeric durations globally and ignores null values.
- [x] Repository aggregation counts only notes with `voice_note_details.status == "created"`.
- [x] Repository aggregation returns zeros for no rows.
- [x] Duration formatting renders zero seconds clearly.
- [x] Duration formatting renders a sub-hour duration without ambiguity.
- [x] Duration formatting renders an exact hour without incorrect residual minutes.
- [x] Duration formatting renders 45,240 seconds as `12 h 34 min`.
- [x] Dashboard summary retains existing notes, documents, sources, and last-capture fields.
- [x] Dashboard HTML includes the two new metric labels and their expected values.
- [x] Pending card HTML links to `/notes?status=created`.
- [x] Existing authenticated dashboard response and security-header assertions continue to pass.
- [x] Manual bounded visual verification checks desktop, tablet, and mobile layouts for overflow, hierarchy, focus visibility, and card balance.

---

### 8. Dependencies

- Existing `voice_notes.duration_seconds` column.
- Existing one-to-one `voice_note_details` relation and `created` status value.
- Existing `VoiceNotesRepository`, `DashboardService`, FastAPI/Jinja dashboard route, and note status filter.
- Existing CSS tokens and responsive breakpoints in `frontend/static/css/app.css`.
- No new package or infrastructure dependency.

---

### 9. Notes

- Metrics are intentionally global and include notes belonging to active and archived sources.
- Seconds below a complete minute may be rounded down for the requested whole-minute format; zero and sub-minute copy must remain understandable.
- The pending metric represents enrichment/processing state, not pending reflections or pending session-document membership.
- Keep the repository query bounded to fields needed for these aggregates; do not reuse `list_web_notes()` with its label hydration or high-limit detail lookup.
- Preserve the current English dashboard copy unless a broader localization request is introduced separately.
- This is a refinement, not authorization to replace the established visual identity or navigation.

---

### 10. project_spec.md Alignment

No changes required. The project specification already includes a read-only web library with dashboard statistics; these metrics refine that existing capability without adding a new core concept, schema, or system boundary.

## Execution Log

- [2026-09-12 22:02] Agent: Planner | Status: in_progress | Confirmed metric definitions, scope, affected files, and test surfaces
- [2026-09-12 22:02] Agent: Planner | Status: completed | Created implementation-ready dashboard recording metrics plan
- [2026-09-12 22:18] Agent: Frontend | Status: in_progress | Started dashboard metric layout and accessibility refinement
- [2026-09-12 22:19] Agent: Backend | Status: in_progress | Started repository and dashboard-service recording metrics implementation
- [2026-09-12 22:20] Agent: Backend | Status: completed | Added paginated recording aggregates, duration formatting, summary fields, and focused coverage; 30 web tests passed
- [2026-09-12 22:24] Agent: Frontend | Status: completed | Added six-metric responsive dashboard, accessible link states, and controller rendering assertions
- [2026-09-12 22:31] Agent: Tester | Status: completed | Reviewed the repository-service-template contract; added pagination and duplicate-relation coverage; 31 focused tests and 651 full-suite tests passed (14 pre-existing warnings)
- [2026-09-12 22:34] Agent: Orchestrator | Status: completed | Verified the rendered dashboard at 1440 px, 768 px, and 390 px widths using a local static fixture backed by the production stylesheet; no overflow, hierarchy, or responsive defects found
