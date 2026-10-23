# Tiresias — CLAUDE.md

Grounded text-to-SQL library for dbt + DuckDB warehouses. It drafts one read-only query,
runs it through a guarded MCP tool, cites its SQL, and abstains when it can't ground an
answer. City apps (Elvis, robbins, gregan, groening) install it and pin a git tag. See
[`README.md`](README.md) for usage, and [`PRD.md`](PRD.md), [`TASKS.md`](TASKS.md) and
[`DECISIONS.md`](DECISIONS.md) for the plan.

## Test command (run before every commit)

```
uv sync --all-extras
uv run pytest -q -m "not slow" && uv run ruff check tiresias tests \
  && uv run ruff format --check tiresias tests && uv run ty check tiresias tests
```

The suite is hermetic. It builds the synthetic Testville city in a temp dir
(`tests/conftest.py`) and needs no warehouse, network or API key. `-m slow` adds the real
fastembed model.

## CLI

```
tiresias check     --config tiresias.yml   config vs dbt artifacts (missing tables, undocumented columns)
tiresias calibrate --config tiresias.yml   grounding score of every gold question, to pick the threshold
tiresias eval      --config tiresias.yml   retrieval recall@k, then the live gold set (needs a key)
tiresias eval --retrieval-only ...         retrieval only, no key
tiresias mcp       --config tiresias.yml   stdio MCP server
```

Exit codes: 0 ok, 1 a check or eval failed, 2 the command could not run. `-v` before the
subcommand logs debug output to stderr (stdout belongs to MCP).

## House rules

- **TDD.** Write the failing test first, then the code. Tests stay **hermetic**: Testville
  only, with no warehouse, network or API key. Mark real-model tests `slow`.
- **No city specifics in `tiresias/`.** No city or agency names and no `mart_`.
  `tests/test_no_city_specifics.py` enforces this. Everything city-specific comes from
  `tiresias.yml`.
- **No default config.** Every module takes the config explicitly. Unknown YAML keys are an
  error.
- **Read-only and abstain-first.** Never loosen the guard: SELECT-only, table/schema
  allowlists, map-only columns rejected, row cap, statement timeout, result cap, locked-down
  read-only DuckDB. A refusal is tested behavior; add a test when you add a refusal.
- **ROCRLL ledger.** Tick TASKS.md checkboxes as you go. DECISIONS.md is append-only, and
  Claude's own calls are marked "drafted by Claude, awaiting Evan's confirmation".
- **Blockers go in `BLOCKED.md`** in the canonical format (`- [ ]`, 🔴/🟡, exact steps for
  Evan to unblock).
- **Branches.** `main` is protected: feature branch + PR, never a direct push. Python 3.12
  and `uv`.

## Do not

- No deploys, merges, tags or releases. Tags (e.g. `v0.1.1`) are Evan's.
- Don't bump the city pins in elvis, robbins, gregan or groening from here; that lives in
  their repos and waits on a tag.
- **Use no keys.** Don't run `tiresias eval` live or the live gold sets, and don't
  recalibrate thresholds against live runs. A public city page needs a dedicated, scoped,
  spend-capped `ANTHROPIC_API_KEY` for that app, never a personal one (see BLOCKED.md).
- Never read `.env` files. No browser automation; verify with tests, curl and logs.
