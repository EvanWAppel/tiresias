# AGENTS.md — tiresias

Instructions for any coding agent working here: Codex, Claude, or others.

## Read first

- **`CLAUDE.md`** — this project's house rules: tooling, boundaries, conventions. Despite the
  name, they apply to every agent. Lines starting with `@` are Claude imports; open the named
  file yourself if the task needs it (`VOICE.md` matters only when writing prose).
- **`PRD.md`** — what the project is. **`TASKS.md`** — the backlog. **`DECISIONS.md`** — why
  it is that way. **`BLOCKED.md`** — what waits on Evan.

## Prime directive

If anything is unclear, stop and ask Evan. Don't guess. Running headless under an
orchestrator's brief: stop and report the question instead.

## Project-specific rules

<!-- Rules that apply only to this project, for agents that won't read CLAUDE.md closely.
     Keep it short; CLAUDE.md stays the source of truth for house rules. -->

<!-- The ROCRLL standing-rules block goes below, injected and kept current by
     `factotum recl-sync`. Don't edit it by hand. -->

<!-- factotum:recl-standing-rules -->
**ROCRLL** — this project follows Requirements → Orchestrate → Check → Review → Loop → Ledger.

- **Requirements.** Draft/keep a `PRD.md` via interview — walk every branch, don't guess.
  The interview also produces the `TASKS.md` grouping and seeds the Ledger.
- **Orchestrate.** Default is linear. Fan out to subagents **only when a task group has ≥3
  genuinely independent tasks**; give each its **own git worktree**, merge back one at a
  time, and remove each worktree and its branch once merged or abandoned.
  **Precondition:** the project must be its own standalone git repo. Worktrees are for
  overlapping-file work — disjoint-file fan-out may use lighter same-tree partitioning.
  **Agents are hands, you're the head:** subagents write code in their worktrees; they never
  inspect raw data or make design/verdict calls — those escalate to the orchestrator.
- **Check.** TDD, test-first. **The human inspects the data; the agent never sees raw data.**
  Run Check **centrally at the orchestrator** at each merge join, not inside each worktree:
  **affected tests + lint + typecheck at each join; the full suite once, before the group's
  final merge to main.**
- **Review.** Independent adversarial review on **every merge to the main line**. Default
  reviewer: a fresh-context same-model subagent; escalate cross-model for high-stakes/security.
  **High-severity findings block, but the human adjudicates them against the primary source** —
  reviewers over-call; never auto-action a finding. Everything below high is advisory.
- **Loop.** Iterate.
- **Ledger.** Record every **decision with a real trade-off** (chose X, rejected Y, why) in a
  `DECISIONS.md` append log. The agent drafts the entry; the human confirms it.

**Guardrails (always on):** TDD-first · nothing external sent/merged/published/deployed
without explicit human approval · the agent never sees raw data · **no autonomous
(Ralph-style) self-feeding loops** · **prime directive — if anything is unclear, stop and ask.**

**Standard artifacts:** `PRD.md` · `TASKS.md` (parallel groups marked) ·
`AGENTS.md`/`CLAUDE.md` · `DECISIONS.md` · `BLOCKED.md`.

<!-- /factotum:recl-standing-rules -->
