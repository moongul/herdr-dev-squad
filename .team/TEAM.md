# Team Operating Protocol (.team/TEAM.md)

## Roles & Permissions

| Role | Primary Responsibility | Edit Permissions |
|---|---|---|
| Controller | Orchestration, prioritization, state tracking, final sign-off | Team docs & `status.json` only; **never** edit product/test code |
| Planner | Requirements analysis, WBS, acceptance criteria, RCA & fix plans | Planning docs & fix plans |
| Architect | Architecture, data models, API/type contracts, refactoring blueprints | Architecture/API specs & contracts |
| Designer | UI/UX flows, design systems (`DESIGN.md`), component specs | Design specs & wireframes |
| Frontend | Browser UI, client state, API integration | Frontend source & targeted tests |
| Backend | APIs, domain logic, DB schemas, auth | Backend source & targeted tests |
| Reviewer | Independent code/design review, defect & security audit | Review reports only; **never** edit product code |
| QA | Test design, execution, independent PASS/FAIL verdict | Test plans/reports only; **never** edit product code |

## Default Model Assignment (Configurable via `.team/agents.json`)
- Controller: Gemini 3.8 Flash (`agy`)
- Planner: Gemini 4 Neon (`agy`)
- Architect: Muse Spark 1.3 (`pi`)
- Designer: Gemini 4 Argon (`agy`)
- Frontend: Gemini 4 Hydrogen (`agy`)
- Backend: Gemini 4 Hydrogen (`agy`)
- Reviewer: Muse Spark 1.3 (`pi`)
- QA: Muse Spark 1.3 (`pi`)

Copy `.team/agents.example.json` to `.team/agents.json` to customize CLIs (`agy`, `pi`, `claude`, `opencode`, `codex`) and models for your environment.

## Task State Machine
- `PENDING` → `IN_PROGRESS` → `REVIEW_REQUESTED` → `QA_READY` → `COMPLETED`
- Exception states: `BLOCKED`, `CHANGES_REQUESTED`, `QA_FAILED`, `RETEST_REQUIRED`, `CANCELLED`

## Complexity-Based Workflows
- **Level 1 (Simple Fix)**: `Controller → Frontend/Backend → (Optional) Reviewer`
- **Level 2 (Standard Feature)**: `Controller → Planner (brief) → Architect or Designer → Frontend/Backend → Reviewer → Scoped QA`
  - **Contract-First**: Whenever Frontend and Backend integrate or share types, `Architect` must lock field names, schemas, and types before implementation begins.
- **Level 3 (Complex / New Project)**: `Controller → Planner → Architect + Designer → Frontend + Backend → Reviewer → QA`
- **Troubleshooting (Round 2+ Failures)**: On repeated QA/Reviewer failures or multi-module contract mismatches, route to `Planner` for Root Cause Analysis (RCA) & Fix Plan before developers patch again.
- **Background Duties**: When idle, `Planner` audits tech debt (`shortcut:`) and edge cases; `Architect` identifies oversized (>500 LOC) modules and prepares refactoring blueprints.

## Shared Task Folder & Pass-by-Reference Protocol
Each task lives under `.team/tasks/<TASK-ID>/`:
- `task.md`, `status.json`, `history.md`, `development-report.md` (or `frontend-report.md` / `backend-report.md`), `review-report.md`, `qa-report.md` / `test-report.md`
- Keep all `herdr` prompts and replies to 3–4 pointer lines (Zero-Dump rule). Full details go in markdown reports only.

## Definition of Done
Only `Controller` sets `COMPLETED`, after verifying:
1. Acceptance criteria met
2. Implementer's targeted test report present
3. Reviewer verdict is `APPROVED` (or documented exception)
4. Risk-appropriate QA verdict is `PASS`
5. Remaining risks/limitations documented
6. Artifacts & `status.json` updated
7. **Memory Sync**: Controller runs `.team/scripts/sync-memory.sh` to index the completed task into SQLite Vector/Graph memory (`memory.db`)

## Multi-Project Operations
- **Isolated Project Spaces**: `.team/projects/<project-id>/` stores per-project `PROJECT.md`, `TASKS.md`, `tasks/`, and `sessions.json`.
- **Interactive Team Hub (`F12` / `./team-hub`)**:
  - Preview projects, inspect live agent statuses & token usage, switch projects (`Enter`), or create & initialize a new project (`n`).
  - CLI summary mode: `./team-hub -s`
- **Project Switch CLI**:
  - Status: `./switch-project.sh`
  - Switch by name: `./switch-project.sh my-app`
  - Switch/create by path: `./switch-project.sh ~/Work/my-app`
  - Keep controller session: `./switch-project.sh <target> --keep-controller`
- **Symlink Consistency**: Root `PROJECT.md`, `.team/TASKS.md`, and `.team/tasks` always point to the active project in `.team/active_project`.

## Agent Knowledge Memory & RAG Search (`memory.db`)
All agents query historical task decisions, code entities, and multi-hop causal chains before editing:
- **Scoped search**: `.team/scripts/search-memory.sh --agent <role> "<query>"`
- **File history**: `.team/scripts/search-memory.sh --agent <role> --file <filename>`
- **Cross-project search**: `.team/scripts/search-memory.sh --agent <role> "<query>" --project all`
- Every query is logged to `memory_access_logs` and displayed in the Web Command Deck (`http://localhost:8080`).
- Only `Controller` runs `.team/scripts/sync-memory.sh` upon task completion; other roles only read/search.
