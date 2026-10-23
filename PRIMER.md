# Tiresias — Primer

## Next session — 2026-10-24 weekend

**Goal.** Tiresias is a grounded text-to-SQL library for dbt + DuckDB warehouses. It drafts one
read-only query, runs it through a guarded MCP tool, cites its SQL, and abstains when it can't
ground an answer. City apps install it and pin a tag: Elvis (live), plus robbins, gregan and groening (in flight).

**Current state (main `bf17f9f`, 2026-10-22).**
- E0–E4 are done. `v0.1.0` is tagged and Elvis runs on it, with the live gold set at 36/36.
- v0.1.1 is merged (`0ae9123`, `pyproject` 0.1.1). It holds the case-insensitive column docs, the
  CTE-scope allowlist fix and the locked-down DuckDB. It is **not tagged yet**, and every city
  still pins v0.1.0 (see BLOCKED.md).
- E5 city PRs are merged (gregan#10 and groening#15 on 2026-10-08, robbins#23 on 2026-10-11; checked
  read-only 2026-10-22). No open PRs in this repo.
- Tests on main: `194 passed, 1 deselected` (the slow one) in about 3 min. ruff, ruff format and ty are clean.
- The repo has no CLAUDE.md. The house rules below come from PRD.md, TASKS.md and DECISIONS.md.

**Test command (every task):**
```
uv sync --all-extras
uv run pytest -q -m "not slow" && uv run ruff check tiresias tests \
  && uv run ruff format --check tiresias tests && uv run ty check tiresias tests
```

### Autonomous tasks, in order

Each task goes on its own feature branch off `origin/main`, ends in its own PR, and is never merged.

1. **Close the LOW `current_setting()` finding** (`reviews/2026-10-05-city-adoption-security.md`,
   last row). Write a failing test first in `tests/test_sql_guard.py`, then make
   `tiresias/sql_guard.py` reject DuckDB settings and introspection functions (`current_setting`,
   `getenv`, `duckdb_*`, `pragma_*`, etc.), keeping the existing P0.9 hostile-input cases.
   *Done when* the new tests pass, the full suite is green, and the review row says "Fixed (vX)".
2. **Add a repo `CLAUDE.md`** that writes down the house rules below, the test command and the
   CLI. *Done when* the file exists and agrees with the README. This is docs only.
3. **Add `CHANGELOG.md`** with release notes for v0.1.0 and v0.1.1, taken from TASKS.md, the reviews and
   `git log`, so they're ready when Evan tags. *Done when* both versions list their changes and
   security fixes, with commit SHAs.
4. **Refresh the TASKS.md E5 ledger.** Read each city PR's state with `gh pr view` (read-only):
   gregan#10, groening#15 and robbins#23 in `EvanWAppel/<city>`. Update the `[~]` lines to match. *Done
   when* every E5 line matches GitHub. Never comment on, push to or merge those PRs.
5. **Bedrock provider behind the shim** (TASKS P3.2). Add an `LLMProvider` implementation using
   the Anthropic SDK's Bedrock client, unit-tested with a fake client, with **no live AWS call**. If
   it needs a new dependency, put it in an optional extra (`tiresias[bedrock]`), and update
   `uv.lock` with `uv lock`. Record the config shape in DECISIONS.md as "drafted by Claude,
   awaiting Evan's confirmation". *Done when* the hermetic tests cover plan, abstain, refusal and
   synthesize through the fake. Size M, so do it last.

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
- **No deploys, merges, tags or releases.** Don't push the `v0.1.1` tag; it's Evan's (BLOCKED.md).
  Don't touch Railway.
- **Don't bump the city pins** in elvis, robbins, gregan or groening. That waits on the tag and
  lives in other repos.
- **Use no keys.** Don't run `tiresias eval` live or the live gold sets, and don't recalibrate
  thresholds against live runs. Any public-page key work waits on the per-city key checklist in BLOCKED.md.
- **Don't add `chat.show_rejections`** or change the Trace expander. That is Evan's decision (BLOCKED.md 🟡).
- Skip the Phase 1 dbt/Snowflake items, the P3.2 per-domain metrics and cross-domain joins, and
  the P2.4 screencast. They are Elvis-side or manual.
- No browser automation, and never read `.env` files. The repo has no git-crypt paths.
