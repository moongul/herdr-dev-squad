# Shared Agent Guidelines (AGENTS.md)

## 1. Language & Communication
- **Always respond in the user's language** (e.g., respond in Korean when prompted in Korean, English when prompted in English). Code identifiers and standard technical terms may remain in English.
- State the conclusion and next action first; document rationale, impact, and verification results concisely.
- Never present uncertain information as fact—mark it explicitly as `Needs Verification`.

## 2. Before Starting Any Task
1. Inspect the project root and current working state.
2. Read `PROJECT.md`, `.team/TEAM.md`, and `.team/TASKS.md`.
3. Read your role guide at `.agents/roles/<role>.md` and any relevant workflow docs.
4. Discover available global and project Skills; if a relevant Skill exists, read its `SKILL.md` before using it.
5. Inspect `.team/tasks/<TASK-ID>/task.md` and `status.json`. If no Task ID exists, request one from Controller or register a new task per team rules.
6. **Pre-Task Knowledge Memory Lookup (RAG)**: Run `.team/scripts/search-memory.sh --agent <your-role> "<keyword>"` (or `--file <filename>`) to review prior design decisions, related tasks, and file modification history before editing. (Each query is automatically logged to `memory_access_logs`.)

## 3. Scope & File Safety
- Stay strictly within your assigned role and task scope.
- **Controller Boundary (No Product Source or Test Edits)**: Controller is the orchestrator, not an implementer. Controller must never directly edit product source code (`src/`, `components/`, `backend/`, etc.) or run unit/E2E tests (`vitest`, `npm test`, `tsc`, etc.). Always delegate implementation and testing to the appropriate role (`frontend`, `backend`, `qa`, etc.).
- Do not concurrently edit files owned by another agent.
- Check existing changes and Git status before overwriting files.
- Never expose secrets, tokens, personal data, or production data in logs, reports, or test fixtures.
- Do not run destructive commands, delete data, reformat entire repos, or mass-update dependencies without explicit approval.
- Respect existing architecture and conventions; avoid unnecessary rewrites or out-of-scope refactoring.

## 4. Skill Usage Rules
- Check both global (`~/.agents/skills/`) and project-level Skills before concluding a Skill is unavailable.
- Always read the installed `SKILL.md` to confirm procedures, constraints, and expected outputs before invoking a Skill.
- Never guess Skill names or commands. If a Skill or tool is unavailable, report it and use a safe fallback.
- For `herdr` messaging, pane control, and agent prompting, follow the official `herdr` CLI/Skill syntax.
- If a Skill conflicts with security rules, user instructions, or role permissions, higher-priority rules win—report the conflict.

## 5. Task Management & Complexity Levels (Token Optimization)
- `.team/` is the durable source of truth for task state. Chat messages do not replace task records.
- Every task must have a unique `TASK-ID`.
- Record task start, status transitions, key decisions, dev reports, review verdicts, QA results, and completion in `.team/tasks/<TASK-ID>/`.
- **Single Writer for `status.json`**: Controller owns `status.json` updates unless explicitly delegated.
- Never assume a delegated task is complete simply because a prompt was sent—verify the output file and agent state.

### Workflow Levels by Task Complexity
To prevent wasted tokens and unnecessary agent handoffs, Controller selects one of three levels:
- **Level 1 (Simple Fix)**: Copy tweaks, CSS adjustments, typos, minor single-file bug fixes
  - Pipeline: `Controller` ➜ `Frontend` or `Backend` ➜ *(optional)* `Reviewer`
  - Skip Planner, Architect, Designer, and QA unless impact widens.
- **Level 2 (Standard Feature)**: New screen, new API endpoint, feature extension, new component
  - Pipeline: `Controller` ➜ `Planner (brief)` ➜ `Selected Design Role (Architect or Designer)` ➜ `Frontend / Backend` ➜ `Reviewer` ➜ `Scoped QA`
  - Reuse existing architecture and design tokens; focus review on the changed surface.
- **Level 3 (Complex Feature / New Project)**: New architecture, multi-module pipelines, breaking schema changes
  - Pipeline: `Controller` ➜ `Planner` ➜ `Architect` + `Designer` ➜ `Frontend` + `Backend` ➜ `Reviewer` ➜ `QA`
  - Full WBS, independent specs, independent review, and real-browser E2E verification.

## 6. Inter-Agent Communication (Pass-by-Reference)
- Use `herdr agent prompt` for all agent-to-agent requests.
- **Strict 3–4 Line Pointer Format (Token Optimization)**:
  - Never paste long specs, source code, or file lists into inter-agent prompts. Store details in `.team/tasks/<TASK-ID>/task.md` (or `api-spec.md`) and send only a compact pointer:
    ```text
    herdr: [TASK-ID] <Role> Task Request
    - Spec: .team/tasks/<TASK-ID>/task.md (or api-spec.md)
    - Report: .team/tasks/<TASK-ID>/<role>-report.md
    - Pre-check: Run .team/scripts/search-memory.sh --agent <role> "<keyword>" before starting
    Implement only your assigned scope and reply with a 3-4 line summary.
    ```
- Log major requests, verdicts, and transitions in `.team/tasks/<TASK-ID>/history.md` or `.team/logs/agent-communication.md`.

## 7. Test Responsibility Split & Completion Criteria
To eliminate redundant test runs and long wait times:
- **Developers (`Frontend` / `Backend`)**:
  - Do **not** run full test suites (`npm test`) or heavy production builds (`npm run build`).
  - Run **targeted unit tests only** (`npx vitest run <changed-test-path>`, 3–5s).
  - Run lightweight type-checks (`npx tsc --noEmit`) instead of full builds.
- **QA (Scope-Based Selective Verification)**:
  - Do **not** blindly spin up browser E2E suites for every change.
  - Do **not** double-verify the same scenario with both Playwright scripts and CLI tools.
  - Skip unrelated packages (backend-only changes skip frontend tests; frontend-only changes skip backend tests).
  - **Backend Only**: Backend regression suite + live API check (`curl`/vitest) — skip browser E2E.
  - **Frontend UI Only**: Frontend regression suite + DOM/console render check as needed.
  - **Full-Stack / Core Interaction**: Regression suites + targeted E2E for the changed user flow.

A task may be marked `COMPLETED` only when:
- Requirements and acceptance criteria are satisfied
- Implementer's targeted test results are recorded
- Required code review is `APPROVED` (or Controller-approved exception recorded)
- Risk-appropriate QA verification is `PASS`
- Remaining risks/limitations are disclosed
- Task artifacts and `status.json` are up to date

## 8. Result Feedback Format (Strict Zero-Dump)
- Write full diffs, file-by-file details, test logs, and risk notes **only** to `.team/tasks/<TASK-ID>/<role>-report.md`.
- Keep `herdr` reply messages to **3–4 lines**:
  ```text
  [TASK-ID] <Role> Complete
  - Status: DONE | APPROVED | CHANGES_REQUESTED | BLOCKED | PASS | FAIL
  - Report: .team/tasks/<TASK-ID>/<role>-report.md
  - Summary: 1-2 line verdict or key result
  Ready for Controller (or next owner).
  ```
