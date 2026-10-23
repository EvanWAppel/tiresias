# Changelog

All notable changes to Tiresias. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). City apps install a git tag, so a version
is only usable once its tag exists.

## [Unreleased]

Not tagged yet. The `current_setting()` guard fix below needs a `v0.1.2` tag before the
cities can pin it (see `BLOCKED.md`).

### Security
- The SQL guard rejects settings, environment and introspection functions anywhere in
  a query (scalar, table-valued and lambda positions): `current_setting`, `getenv`,
  `getvariable`, `which_secret`, `version()`, `current_database/schema/catalog/user/query`,
  `query`/`query_table`, `glob`, and every `duckdb_*`, `pragma_*` and `pg_*` function.
  Closes the LOW `current_setting()` finding in
  `reviews/2026-10-05-city-adoption-security.md` (`fd05cba`).
- The chat's trace panel no longer shows guard or DuckDB rejection text by default:
  a rejected step reads `execute: rejected (details hidden)`, so anonymous visitors
  on a public page don't see schema detail from error messages (review E3 #6). Set
  `chat.show_rejections: true` in `tiresias.yml` to show the full text, e.g. on a
  private page.

### Added
- `chat.show_rejections` config key (default `false`) and `tiresias.chat.public_trace`.

## [0.1.1] - 2026-10-07

Merged as PR #5 and tagged `v0.1.1` on `0ae9123` (2026-10-23). Upgrade from v0.1.0,
which has the HIGH allowlist bypass below; the city pin bumps (gregan, groening,
robbins, elvis) are open as one PR per city repo.

### Security
- **HIGH: CTE-scope allowlist bypass.** The guard exempted any table whose name matched
  a CTE anywhere in the query, but DuckDB resolves CTE names by scope, so a CTE defined
  inside a subquery let an outer reference reach an excluded table or a local file
  through `run_validated_sql`. A name now counts as a CTE only when a WITH clause in its
  own ancestry defines it. Tests cover the nested, file-path and union-branch variants
  plus legitimate CTE patterns (`9dcf11a`).
- **HIGH (defense in depth): locked-down DuckDB.** Tiresias no longer queries through a
  plain read-only connection. It opens its own in-memory DuckDB instance, ATTACHes the
  warehouse `READ_ONLY`, disables external access and extension auto-install/auto-load,
  and locks the configuration. File reads fail even without the guard, and the
  instance coexists with the city app's own connection (`9dcf11a`).
- **LOW: positional alias lists over map-only tables.** A column-alias list such as
  `t(a, …, x)` could rename a map-only column past the name and DESCRIBE checks. Alias
  lists are now rejected in queries over tables that have map-only columns (`9dcf11a`).

### Fixed
- dbt column docs match catalog columns case-insensitively. dbt lowercases unquoted
  column keys in `manifest.json` while DuckDB keeps the created case, so mixed-case
  columns silently lost their descriptions (`12049e6`).

### Changed
- Version bumped to 0.1.1 in `pyproject.toml` and `tiresias.__version__` (`12049e6`).

## [0.1.0] - 2026-10-04

First standalone release, tagged on `bbb34d6`. Elvis runs on it (live gold set 36/36).
The engine was extracted from Elvis with its history (Phases 0–3); this release makes
it a config-driven library any dbt + DuckDB city app can install.

### Added
- **Config-driven engine** (`1fe276b`). A `tiresias.yml` schema (Pydantic,
  `tiresias/config.py`) holds the city, blurb, paths, table scope, map-only columns,
  examples, planner notes, metrics and gold paths, threshold and limits, and chat copy.
  Unknown keys and allowed/excluded overlaps are errors. Every module takes the config
  explicitly; nothing defaults to a city, and `tests/test_no_city_specifics.py` keeps
  city and agency names out of `tiresias/`. Elvis's constants, metrics and gold sets
  moved to `examples/elvis/`.
- **Hermetic test suite and CI** (`1fe276b`). The synthetic Testville city
  (`tests/fixtures/testville`, built by `tests/conftest.py`) needs no warehouse,
  network or API key. CI runs ruff, ruff format, ty and pytest.
- **Packaging** (`a788176`). `pyproject.toml` (Python 3.12, uv_build), a `tiresias`
  console script, and a `tiresias[streamlit]` extra. The wheel holds only the engine.
- **CLI** (`a788176`): `check` (config vs dbt artifacts), `calibrate` (grounding score
  of every gold question), `eval` (retrieval recall@k, then the live gold set) and `mcp`
  (stdio server). Engine harness in `tiresias/evals.py`.
- **`render_chat(config)`** (`a788176`), a Streamlit chat page with the public abuse
  guards (input length, per-session and daily caps, from `limits:` with
  `TIRESIAS_MAX_*` overrides).
- MIT license (`c83ebad`).

Carried over from the Elvis phases: hybrid dense + BM25 retrieval fused with RRF, a
calibrated grounding threshold, the governed metric registry, the MCP server
(`run_validated_sql`, `list_tables`, `profile_column`, `get_metric`, catalog and metric
resources), the LangGraph `retrieve → plan → execute → synthesize` agent with an
abstain terminal, and the sqlglot SELECT-only guard with allowlists, row cap, EXPLAIN,
statement timeout, result cap and map-only column rejection.

### Fixed
- E1+E2 review (`cc86d92`, `reviews/2026-10-04-e1-e2-config-engine.md`): map-only
  columns are a read-only mapping, so one component can no longer disable hiding for
  all the others (MED); `with_limits` validates like the YAML; range checks on limits
  and the threshold (no zero caps, negative timeouts or NaN); `~` expanded in paths;
  clearer bare-table-name rule in the planner prompt.
- E3 review (`6baeb65`, `reviews/2026-10-04-e3-packaging.md`): the chat agent is cached
  on the full config, so an edited `tiresias.yml` no longer serves a stale allowlist or
  threshold (MED); a command that cannot run exits 2, not 1 (MED); one crashing gold
  case no longer aborts the run (MED); `eval --retrieval-only` without retrieval gold
  exits 2; the daily limiter keeps its count when the cap changes; gold files are
  range-checked with unique ids.

### Security
- Pre-extraction hardening shipped in this release: the enforced statement timeout
  (review S1) and map-only JSON columns hidden from the agent and rejected by the guard,
  with a 256 KB result cap (review S2) (`d7338c3`, `4961691`,
  `reviews/2026-10-03-tiresias-all-domains.md`).
- Known issue, fixed in 0.1.1: the HIGH CTE-scope allowlist bypass.

[Unreleased]: https://github.com/EvanWAppel/tiresias/compare/0ae9123...HEAD
[0.1.1]: https://github.com/EvanWAppel/tiresias/compare/v0.1.0...0ae9123
[0.1.0]: https://github.com/EvanWAppel/tiresias/releases/tag/v0.1.0
