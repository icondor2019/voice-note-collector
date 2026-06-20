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
| graphify **(global, mandatory)** | **Any codebase exploration, architecture question, or file-relationship query — use BEFORE reading/grepping files. `graphify-out/` is gitignored but exists locally — always check for `graphify-out/graph.json` and run `graphify query` first (absent on fresh clones until `/graphify` runs).** | ~/.config/opencode/skills/graphify/SKILL.md |
| fastapi-structure | Creating new FastAPI project or adding new modules | .opencode/skills/fastapi-structure/SKILL.md |
| fastapi-controller-pattern | Adding API endpoints or REST routes | .opencode/skills/fastapi-controller-pattern/SKILL.md |
| fastapi-testing | Writing FastAPI endpoint tests | .opencode/skills/fastapi-testing/SKILL.md |
| configuration-management | Accessing env vars or adding new settings | .opencode/skills/configuration-management/SKILL.md |
| architecture-awareness | Making architectural decisions or checking existing patterns | .opencode/skills/architecture-awareness/SKILL.md |
| python-execution | Running Python, pip, or pytest commands | .opencode/skills/python-execution/SKILL.md |
| execution-logging | Logging agent actions in feature specs | .opencode/skills/execution-logging/SKILL.md |

## Tools
| Tool | Trigger | Path |
|------|---------|------|
| engram | Always check engram MCP when starting a fresh session or when needing to recall past interactions | MCP engram |