# Review — E1+E2 config-driven engine (PR #1)

Reviewer: fresh-context same-model subagent (adversarial), 2026-10-04.
Scope: `git diff main..e1-config-engine`. **No HIGH findings.** Read-only boundary
confirmed unchanged by probe queries (file readers, metadata functions, row-as-struct,
`columns()`, `* exclude`, CTE named like an excluded table, unknown catalog). The
Elvis reference config was AST-diffed against the old constants: identical.

| # | Sev | Finding | Disposition |
|---|-----|---------|-------------|
| 1 | MED | `map_only_columns` was a mutable dict inside the frozen config; `pop` disabled hiding for every component sharing it (confirmed; same as on main, but contradicts the frozen promise) | **Fixed**: read-only `MappingProxyType`; test |
| 2 | LOW | `with_limits` skipped validation (a typo'd cap silently did nothing) | **Fixed**: validates like the YAML; test |
| 3 | LOW | No range checks (`max_rows: 0`, negative timeout, `threshold: nan`) | **Fixed**: positive ints/floats, threshold in [0, 1], no NaN; tests |
| 4 | LOW | `~` not expanded; paths only resolve through `load_config` | **Fixed** `~`; direct construction stays the caller's job |
| 5 | LOW | Prompt said "bare name, exactly as listed" but the listing shows `main.x` | **Fixed**: "bare table name, without the schema prefix" |
| 6 | LOW | `schemas` never checked against the catalog's schema | E3: `tiresias check` flags it |
| 7 | LOW | stdio entry point gone until the CLI exists | E3 (`tiresias mcp`) |
| 8 | LOW | `views/tiresias.py` now raises (no config) | E3 (`render_chat` replaces it) |
| 9 | LOW | Coverage: Elvis config untested; only one map-only table; classification check not ported | **Fixed** first two (Elvis load+grounding test; second map-only table in Testville). Classification stays city-side |

Fixing #1 test-first reproduced the bug live: the new mutation test popped the
shared session config and broke every later map-only test until the fix landed.
