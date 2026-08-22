# Agent Skills Index
When working on this project, load the relevant Skill(s) BEFORE writing any code.

## How to Use
Check the trigger column to find skills that match your current task
Load the skill by reading the SKILL.md file at the listed path
Follow ALL patterns and rules from the loaded skill
Multiple skills can apply simultaneously


## Agents

| Agent | Trigger | Path |
|-------|---------|------|
| orchestrator | Always first - coordinates workflow | .opencode/agents/orchestrator.md |
| planner | Clarify requirements and create feature spec | .opencode/agents/planner.md |
| backend | Implement backend logic (FastAPI/Python) | .opencode/agents/backend.md |
| frontend | Build UI components | .opencode/agents/frontend.md |
| tester | Write tests and validate behavior | .opencode/agents/tester.md |
| general | Easy tasks, codebase exploration, ad-hoc solutions | .opencode/agents/general.md |
| archive | Close completed feature | .opencode/agents/archive.md |


## Skills

| Skill | Trigger | Path |
|-------|---------|------|
| graphify **(global, mandatory)** | **Any codebase exploration, architecture question, or file-relationship query — use BEFORE reading/grepping files. Check the local `graphify-out/graph.json` artifact first, even though it is gitignored; use its recorded interpreter for the query and do not use CLI `PATH` presence as the availability check.** | ~/.config/opencode/skills/graphify/SKILL.md |
| fastapi-structure | Creating new FastAPI project or adding new modules | .opencode/skills/fastapi-structure/SKILL.md |
| fastapi-controller-pattern | Adding API endpoints or REST routes | .opencode/skills/fastapi-controller-pattern/SKILL.md |
| fastapi-testing | Writing FastAPI endpoint tests | .opencode/skills/fastapi-testing/SKILL.md |
| configuration-management | Accessing env vars or adding new settings | .opencode/skills/configuration-management/SKILL.md |
| architecture-awareness | Making architectural decisions or checking existing patterns | .opencode/skills/architecture-awareness/SKILL.md |
| python-execution | Running Python, pip, or pytest commands | .opencode/skills/python-execution/SKILL.md |
| execution-logging | Logging agent actions in feature specs | .opencode/skills/execution-logging/SKILL.md |

## Mandatory Graphify Preflight

Graphify is the repository's first source of codebase context. This rule is
mandatory for architecture questions, codebase exploration, file-relationship
queries, implementation context, testing context, and any request that asks
how existing code works.

`graphify-out/graph.json` is a local filesystem artifact. It is intentionally
listed in `.gitignore`, but git tracking is irrelevant to whether it exists and
must not be used as an availability check. In this repository, treat the
artifact as present when the filesystem check succeeds.

Before reading, grepping, globbing, or otherwise scanning repository source:

1. Load `~/.config/opencode/skills/graphify/SKILL.md`.
2. Resolve the repository root and check
   `<repository-root>/graphify-out/graph.json`.
3. If the graph exists, query it immediately for the task's actual question.
   Do not first run `which graphify`; the standalone executable is not the
   graph artifact.
4. Prefer the interpreter recorded in
   `graphify-out/.graphify_python`:

   ```bash
   ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   GRAPH="$ROOT/graphify-out/graph.json"
   PYTHON_FILE="$ROOT/graphify-out/.graphify_python"
   PYTHON=""
   if [ -f "$PYTHON_FILE" ]; then
     PYTHON="$(tr -d '\r\n' < "$PYTHON_FILE")"
   fi
   if [ -n "$PYTHON" ] && [ -x "$PYTHON" ]; then
     "$PYTHON" -m graphify query "<task question>"
   elif command -v graphify >/dev/null 2>&1; then
     graphify query "<task question>"
   else
     # Use the NetworkX graph.json fallback described by the graphify skill.
     # Do not replace this with a raw repository scan.
   fi
   ```

5. Only if the graph artifact is genuinely absent may the agent follow the
   graphify skill's initialization or fallback instructions. Report the exact
   checked path and current working directory; never report "Graphify
   unavailable" merely because the CLI is not on `PATH`.

The orchestrator must run this preflight before delegating context-dependent
work and include the query result in prompts for agents without bash access.
Delegated agents must not repeat a repository-wide scan when graph context was
already provided.

## Tools
| Tool | Trigger | Path |
|------|---------|------|
| engram | Always check engram MCP when starting a fresh session or when needing to recall past interactions | MCP engram |
