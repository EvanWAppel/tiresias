# Decisions

Append-only log of decisions with a real trade-off (ROCRLL Ledger). Decisions made
while Tiresias lived inside Elvis remain in Elvis's `DECISIONS.md`.

## 2026-10-04 — Extract Tiresias into a standalone library (confirmed by Evan)

Interview decisions: a **library** each city app installs and pins (rejected: one
shared service: warehouses would have to be shipped to it, and it would be a
cross-city single point of failure); per-city **`tiresias.yml`** (rejected: a
Python settings module); the Streamlit chat with its abuse guards as an
**optional extra** (rejected: each city maintaining its own); **history preserved**
via `git filter-repo` (rejected: fresh start); **public** repo named `tiresias`
(Evan's older private utilities repo was renamed to `tiresias-tools` to free the
name); planning docs **move here**.

Extraction detail: Elvis's original planning brief was never tracked there and
is not carried over; `PRD.md` here is a new, engineering-only document.

## 2026-10-04 — Rollout order and robbins' existing text-to-SQL (confirmed by Evan)

Published `EvanWAppel/tiresias` (public, standard protection) and kept the phase
order: **Elvis adopts v0.1.0 first** (E4), then robbins → gregan → groening
(rejected: going straight to the siblings, which would lose Elvis's 36/36 live
eval as proof that the extraction kept the same behavior). In robbins, **Tiresias
replaces** `nl_sql.py` / `sql_safety.py` / `semantic.py` (rejected: running
alongside, which leaves two text-to-SQL paths with separate guards to maintain);
the old modules go once robbins' gold set passes.

## 2026-10-04 — E1/E2 shape of the config-driven engine (drafted by Claude, awaiting Evan's confirmation)

- **E1 and E2 in one branch.** Removing city specifics test-first needs a warehouse
  to test against, so the synthetic fixture city came first (rejected: E1 against
  Elvis's real warehouse, which would tie the suite to one city again).
- **Config beyond the PRD list:** `planner_notes` (city caveats appended to the
  planner prompt, e.g. "calls for service are not confirmed crimes") and
  `chat.example_questions` (rejected: keeping those caveats in the engine prompt,
  which is the city leak E1 removes). Unknown YAML keys are an error (rejected:
  ignoring them, since a typo in the allowlist key would silently widen or empty scope).
- **No default config anywhere.** Every module takes the config explicitly
  (rejected: a module-level default, which is how a city sneaks back in).
- **Elvis's data lives in `examples/elvis/` until E4** (rejected: deleting it now
  and rebuilding it in Elvis later from git history).
- The prompt wording changed slightly where it named Elvis tables; E4's live
  36/36 run is the check that behavior held.

## 2026-10-04 — E3 CLI and chat shape (drafted by Claude, awaiting Evan's confirmation)

- **Added `tiresias check`** beyond the PRD's three commands: a static check of
  `tiresias.yml` against the city's dbt artifacts, including undocumented
  columns. It is the "column docs first" gate for gregan and groening (rejected:
  each city writing its own artifact tests, as Elvis did).
- **`tiresias eval` without a key exits 2** rather than skipping (rejected: the old
  pytest skip, which made a missing key look like a pass). `--retrieval-only`
  runs the keyless half.
- **The live gold eval is a CLI, not a pytest module**, so cities run it without
  vendoring tests (rejected: shipping a pytest plugin).
- **Chat caps:** `limits:` in the YAML, overridable by the same `TIRESIAS_MAX_*`
  env vars Elvis already uses on Railway (rejected: env-only, which hides each
  city's defaults from review).
