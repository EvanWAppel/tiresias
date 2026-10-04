# Review — Tiresias all-domains expansion (2026-10-03)

**Change under review:** commit `d57b8a5` (Orchestrate + Check), branch
`feat/tiresias-all-domains`. Widens Tiresias from 4 restaurant marts to 30.

**Reviewers** (independent, fresh context, read-only; no `.env`, no raw data,
no browser, no paid eval):

- **Correctness / grounding:** Claude Opus, same model as the author.
- **Security:** Claude Sonnet, a different model. Escalated because the change
  widens the table allowlist on a public, unauthenticated endpoint.

**Adjudication:** Evan, 2026-10-03. The orchestrator spot-checked the main
claims against the primary source (`build_warehouse.py`, mart SQL) before
adjudication. Neither reviewer demonstrated a HIGH-severity path to harm.

## Correctness review

| # | Sev | Finding | Verified against | Decision |
|---|---|---|---|---|
| C1 | med-high | `mart_road_construction.is_full_closure` documented as "source flags full closure". In fact it is null for the CLV/Henderson CIP rows; only NDOT 511 rows set it, and NDOT loads only with the 511 key. Henderson writes one row per path segment. The gold case `road_full_closures` rewards a meaningless 0. | `build_warehouse.py:932,1101` | Fix |
| C2 | med | `mart_crime_map_sample` is a random 12k-row sample yet is allowlisted. It is the only crime table with address/date, so it invites ~1% undercounts. | `mart_crime_map_sample.sql` | **Exclude** (map-only) |
| C3 | med | `mart_tract_metrics.record_count` documented "null when unavailable". Partial/unavailable tracts in fact carry the raw observed count when any records exist, else null. | `mart_tract_metrics.sql:13` | Fix |
| C4 | med | Gaming-revenue exemplar (`ILIKE 'Gaming Revenue%'`) double-counts the Clark County roll-up; the colon in the name is optional. | `views/tourism.py:58-59` | Fix |
| C5 | med | Short-term rental docs: NLV `status` is a fixed 'Approved', `business_name` is the owner, `issued_date` is the approval date; Henderson `category` is a derived 'Max occupancy N'. | `build_warehouse.py:539-568` | Fix |
| C6 | med | Data periods are undocumented (crime = 2025–2026), so out-of-period questions return a confident 0. | `build_warehouse.py:80` | Fix (docs + gold case) |
| C7 | med | Dropping `ood_crime` removed the calls≠crimes trap. Its score (0.598) was the "lowest answerable" calibration figure. There are no cases for the new prompt caveats. | gold set, calibration log | Fix |
| C8 | low-med | Air-quality `parameter` values are set by our loader ('PM2.5', 'Ozone'), not by the source; `avg_concentration` mixes units. | `build_warehouse.py:140` | Fix |
| C9 | low-med | Road `url`/`category`/`road_name`/`contractor` vary by source (Henderson url = layer endpoint, category hard-coded, road_name null; NDOT contractor = reporting org). | `build_warehouse.py` | Fix |
| C10 | low | `mart_parks.has_water`: CLV value is a spatial join, not a published flag; Henderson derives it from swimming/water-play fields. | `build_warehouse.py` | Fix |
| C11 | low | Small doc errors: origin upper-casing is ours; invented inspection-type examples; grade value set incomplete; "block-level address" unsupported. | staging SQL/yml | Fix |
| C12 | low | Catalog tests repeat each other; nothing forces a new mart to be classified. | `test_catalog.py` | Fix |
| C13 | low | Retrieval recall inflated by substring matching on multi-table exemplar refs. | `test_retrieval_quality.py` | Fix |
| C14 | low | Stale "Phase 0" text; exemplar count stated as 22 (actually 21 new). | `provider.py`, `metrics.py`, `metrics.yml`, tasks | Fix |
| C15 | low | Threshold comment overstates margin; it depends on the removed crime question. | `retrieval.py` | Fix (recalibrate comment) |

Speculative (not actioned; needs data inspection by a human): whether TIGER
places include CDPs in `cities_json`; whether `jurisdiction = 'Las Vegas'`
STRs are City or unincorporated-county licenses; exact LVCVA metric spellings.

## Security review

| # | Sev | Finding | Verified against | Decision |
|---|---|---|---|---|
| S1 | med | `statement_timeout_s` is declared but never enforced. A guard-approved aggregate over a 3-way cross join ran more than 4 minutes. The gap predates this change; the widening makes it easier to hit. | `config.py:97` (no readers) | Fix in this PR: watchdog + `conn.interrupt()` |
| S2 | low-med | Large map JSON columns (`geometry_json` ≤ ~320 KB/row, `path_json`) are selectable; the "do not select" note is a hint, not a rule. | guard is table-level only | Pending Evan |
| S3 | info | Alias spoofing is cosmetic only; the guard resolves real table names. | fuzzing | No change |

**Attacks tried and correctly blocked (~45):** CTE/subquery shadowing; `read_csv*`
and `glob`; `pragma_*` and `duckdb_*()`; `information_schema`; recursive CTEs;
`generate_series`/`range`; set operations against disallowed sources;
case-varied and quoted identifiers; comments; `COPY`; `INSTALL`/`LOAD`; `SET`;
`CALL`; `EXPORT DATABASE`; stacked statements; `ATTACH`; cross-catalog
qualification. There is no prompt-injection path to an action: the graph runs a
single query and a single synthesis. Nothing leaks to the UI, and the abuse
caps still bound spend.

## Outcomes (Loop)

All "Fix" decisions are implemented in the Loop commit. Verification: 62 unit
tests and 24 app tests green; ruff and ty clean; `dbt build --select marts`
PASS=87 with WARN=1 (the road end-after-start warning, which predates this
change); live eval **36/36** (Opus 4.8).

| # | Outcome |
|---|---|
| C1 | Road docs rewritten per source (grain = segment; `is_full_closure` NDOT-only); gold case replaced with `henderson_road_projects`; road exemplar updated. |
| C2 | `mart_crime_map_sample` moved to `EXCLUDED_TABLES` (29 queryable marts). |
| C3 | `record_count` doc matches the SQL; new gold case `tract_zero_parks` requires `coverage` in the SQL (new `sql_must_contain` check). |
| C4 | Gaming exemplar and `metric` doc: exclude the Clark County total when summing; colon optional. |
| C5 | STR docs per jurisdiction. |
| C6 | Coverage periods in crime/marriage/air-quality descriptions; planner told to abstain outside a table's period; gold `out_of_period_crime`. |
| C7 | Gold `ood_crimes_downtown` restored as an abstain case. |
| C8 | Exact 'PM2.5'/'Ozone' values; per-pollutant units; no cross-parameter comparison. |
| C9, C10, C11 | Docs corrected per source. |
| C12 | Test: every built `mart_*` is in exactly one of ALLOWED / EXCLUDED; duplicate tests removed. |
| C13 | Exemplars carry structured `grounds`; recall matches exactly (still 21/21). A test requires every corpus doc to ground to real tables/metrics. |
| C14 | Stale "Phase 0" text removed (provider, metrics, metrics.yml, mcp_server, sql_guard, evals). |
| C15 | Recalibrated: generic off-topic 0.43–0.555, answerable 0.61–0.83, subtle unanswerable 0.575–0.68. Threshold stays 0.56; comment states the planner does the borderline work. |
| S1 | Watchdog `threading.Timer` → `cursor.interrupt()` at `statement_timeout_s` (15s), raising `QueryTimeoutError` (DuckDB error chained); MCP returns `{ok: false}`. Tests: a runaway 3-way cross join is cut off at 0.5s, fast queries are unaffected, the connection stays usable, and a timeout over MCP is structured. |
| S2 | Pending Evan's decision (see `BLOCKED.md`). |
| S3 | No change. |
