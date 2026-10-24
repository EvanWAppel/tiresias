# Tiresias — Primer

## Next session — 2026-10-24 weekend

**Goal.** Tiresias is a grounded text-to-SQL library for dbt + DuckDB warehouses. It drafts one
read-only query, runs it through a guarded MCP tool, cites its SQL, and abstains when it can't
ground an answer. City apps install it and pin a tag: Elvis (live), plus robbins, gregan and groening (in flight).

**Current state (main `1efa91d`, 2026-10-23).**
- E0–E4 are done. `v0.1.0` is tagged and Elvis runs on it, with the live gold set at 36/36.
- `v0.1.1` is **tagged** on `0ae9123` (Evan, 2026-10-23). Pin-bump PRs from v0.1.0 to v0.1.1
  were opened 2026-10-23 in gregan, groening, robbins and elvis (TASKS E5 `[~]`; merging is
  Evan's); robbins' merged as robbins#28.
- The weekend run (PR #8, merged 2026-10-23) did all five tasks from the 2026-10-22 primer
  (see below). #10 then added `chat.show_rejections` (default `false`) so the public Trace
  panel hides rejection text (Evan's call from blocker triage), and cleared the tag and
  per-city key blockers. `main` now carries Unreleased changes (the `current_setting()` guard
  fix `fd05cba` and the hidden rejection text) that wait on a `v0.1.2` tag (BLOCKED.md).
- E5 city PRs are merged (gregan#10, groening#15, robbins#23). No open PRs in this repo.
  CI on main green.
- Tests on main (measured 2026-10-22, before #8 and #10): `194 passed, 1 deselected` (the slow
  one) in about 3 min; ruff, ruff format and ty clean. Both PRs added tests, so re-measure.
- The repo now has a `CLAUDE.md` (added in #8) with the house rules, test command and CLI.

**Test command (every task):**
```
uv sync --all-extras
uv run pytest -q -m "not slow" && uv run ruff check tiresias tests \
  && uv run ruff format --check tiresias tests && uv run ty check tiresias tests
```

### Autonomous tasks, in order

All five tasks from the 2026-10-22 primer are done, merged in PR #8:

1. ~~Close the LOW `current_setting()` finding~~ (`fd05cba`, plus `c554490` pinning the
   introspection rejections to the function-ban error).
2. ~~Add a repo `CLAUDE.md`~~.
3. ~~Add `CHANGELOG.md`~~ (v0.1.0 and v0.1.1; #10 added the Unreleased section).
4. ~~Refresh the TASKS.md E5 ledger~~.
5. ~~Bedrock provider behind the shim~~ (P3.2, `e57d8df`).

No further autonomous tasks are queued in this primer. The next step, cutting v0.1.2, starts
only when Evan says "cut v0.1.2" (BLOCKED.md); open items otherwise live in TASKS.md.

### House rules
- **TDD.** Write the failing test first. Tests stay **hermetic**: the synthetic Testville city in
  `tests/conftest.py`, with no warehouse, network or API key. Mark real-model tests `slow`.
- **No city specifics in `tiresias/`.** No city or agency names and no `mart_`.
  `tests/test_no_city_specifics.py` enforces this. Everything city-specific comes from `tiresias.yml`.
- **No default config.** Every module takes the config explicitly. Unknown YAML keys are an error.
- **Read-only and abstain-first.** Never loosen the guard: SELECT-only, allowlists, row cap,
  timeout, result cap, locked DuckDB. A refusal is tested behavior.
- **ROCRLL ledger.** Tick TASKS.md checkboxes as you go. DECISIONS.md is append-only and marks
  Claude's calls as "drafted by Claude, awaiting Evan's confirmation". Blockers go in BLOCKED.md
  in the canonical format.
- `main` is protected. Use feature branches and PRs, Python 3.12 and `uv`.

### Do NOT
- **No deploys, merges, tags or releases.** Don't push a `v0.1.2` tag; tagging is Evan's (BLOCKED.md).
  Don't touch Railway.
- **Don't bump the city pins** in elvis, robbins, gregan or groening. The v0.1.1 bumps are already
  open or merged, the next round waits on the v0.1.2 tag, and both live in other repos.
- **Use no keys.** Don't run `tiresias eval` live or the live gold sets, and don't recalibrate
  thresholds against live runs (the per-city key blockers were cleared in #10; TASKS.md keeps
  live gold evals behind Evan's gold-set review).
- **Don't change the Trace expander defaults.** `chat.show_rejections` (default `false`) records
  Evan's call (#10, DECISIONS.md).
- Skip the Phase 1 dbt/Snowflake items, the P3.2 per-domain metrics and cross-domain joins, and
  the P2.4 screencast. They are Elvis-side or manual.
- No browser automation, and never read `.env` files. The repo has no git-crypt paths.
