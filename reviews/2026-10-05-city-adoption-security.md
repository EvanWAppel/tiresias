# Security findings from the city-adoption reviews (2026-10-05)

Found by the fresh-context reviewers of gregan#10 and groening#15; reproduced by
the orchestrator on the fixture city before fixing. Fixed in v0.1.1.

| Sev | Finding | Fix |
|-----|---------|-----|
| **HIGH** | **CTE-scope allowlist bypass.** The guard exempted any table whose name matched a CTE *anywhere* in the query, but DuckDB resolves CTE names by scope: a CTE defined inside a subquery does not cover an outer reference, which then resolves to the real table or a file path. Reproduced: an excluded table read (250 rows) and a local CSV read through `run_validated_sql`. Elvis was live with a key on v0.1.0. | `_is_cte_reference`: a name counts as a CTE only if a WITH clause in its own ancestry defines it. Tests for nested, file-path and union-branch variants plus legitimate CTE patterns. |
| HIGH (defense in depth) | The read-only connection still allowed external access (file/URL reads, extension auto-install). | Tiresias now uses its own in-memory DuckDB instance that ATTACHes the warehouse `READ_ONLY`, then disables external access and extension auto-install/load and locks the configuration. (Opening the file with a different config conflicts with the city app's own connection, so a separate instance is required.) Tests: file reads fail even without the guard; config can't be unlocked; coexists with an app connection. |
| LOW | Positional column-alias list (`t(a, …, x)`) renamed a map-only column past the name and DESCRIBE checks. | Alias lists rejected in queries over tables with map-only columns. |
| LOW | `current_setting()` reveals DuckDB settings (paths, no secrets). | Open; follow-up. |

Verified against Elvis's real warehouse: `tiresias check` clean; typical and multi-CTE
queries run; the bypass, the rename and `read_csv` are blocked. 195 tests green.
