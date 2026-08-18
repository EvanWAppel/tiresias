# Tiresias — Task Board

Small, checkboxed steps driven from `TIRESIAS-PRD.md` (RECL: Requirements → tasks).
Work off a feature branch; **do not commit/push without Evan's say-so.**

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[?]` blocked/decision

---

## Phase 0 — vertical slice (restaurant inspections, whole stack, deployed)

**Slice goal:** a stranger asks a restaurant-inspection question → gets a cited,
SQL-backed answer live; an out-of-domain question → a clean abstention; a ~15-case
eval set runs and passes locally.

**Domain marts (real, confirmed):** `mart_restaurants`, `mart_inspection_violations`,
`mart_top_violations`, `mart_inspections_over_time`.

**Canonical Phase-0 metric:** `restaurant_failure_rate` —
`failed_inspections / total_inspections`, where `failed_inspections = downgrades +
closures`. Sourced verbatim from `mart_restaurants.sql:55-58`; the registry points
to the mart column `failure_rate_pct`, it does not reinvent the arithmetic.

### P0.0 — Scaffolding & decisions
- [x] Confirm open decisions that gate Phase 0 (embeddings = **fastembed/ONNX**;
      vector store = DuckDB-native/in-memory cosine; semantic layer = YAML registry;
      no tracing in P0; same repo, `tiresias/` package).
- [x] Create feature branch (`tiresias-phase0`) for Tiresias work.
- [x] `uv add` runtime deps: `anthropic`, `langgraph`, `mcp`, `fastembed`
      (`onnxruntime<1.24`), `pydantic`, `pyyaml`. `uv add --dev`: `pytest`,
      `pytest-asyncio`, `ty`. **Pinned project to Python 3.12** (`.python-version`,
      `requires-python>=3.12,<3.13`) to match Railway prod + satisfy onnxruntime
      Intel-Mac wheels. Elvis + Tiresias imports smoke-tested green on 3.12.
- [x] Create `tiresias/` package skeleton + `tiresias/__init__.py` + `config.py`
      (db path, row/cost caps, allowed schemas). *(model id lives in provider.py, P0.5)*
- [x] Add `tiresias/db.py`: read-only DuckDB connection (mirror `app_db.py`, no Streamlit).
      Tests: reads real rows, write physically blocked, missing-warehouse raises clearly.

### P0.1 — Semantic layer (metric registry)
- [x] `tiresias/metrics.yml`: one metric `restaurant_failure_rate` (name → grain →
      SQL expression → description → source columns/tables). Arithmetic verbatim from mart.
- [x] `tiresias/metrics.py`: typed loader (pydantic), `get_metric(name)`; unit tested.

### P0.2 — Catalog (schema truth from dbt artifacts)
- [x] `tiresias/catalog.py`: reads `target/catalog.json` (types) + `manifest.json`
      (descriptions) → typed table/column records for the 4 restaurant marts only.
- [x] Regenerated `catalog.json` via `dbt docs generate`. Loader unit tested (types,
      docs, allowlist bound). *(Deploy: catalog.json is gitignored → P0.8 must ensure
      `dbt docs generate` runs in the Docker build so retrieval has real types.)*

### P0.3 — Retrieval (minimal dense)
- [x] `tiresias/retrieval.py`: corpus (4 tables' column docs + metric + 5 NL exemplars),
      embed once, in-memory cosine top-k. Embedder behind a Protocol (offline FakeEmbedder
      in tests; real fastembed in a `slow` test). `GROUNDING_THRESHOLD=0.62` calibrated
      from measured bge scores (in-domain 0.74-0.84 vs out 0.48-0.56). 20 tests green.

### P0.4 — MCP server + SQL guard
- [x] `tiresias/sql_guard.py`: sqlglot-based — SELECT-only, single-statement,
      allowlisted schemas/tables, CTE-aware, row cap injected, `EXPLAIN` validates
      against the live catalog. 15 tests (DDL/DML, multi-statement, unknown table,
      disallowed schema, limit capping, hallucinated column).
- [x] `tiresias/tools.py`: shared core (`run_validated_sql`, catalog/metrics text) —
      one implementation, two surfaces.
- [x] `tiresias/mcp_server.py` (mcp 2.0 `MCPServer`): **resources** (catalog +
      metric registry) + **tool** `run_validated_sql`; guard failures returned as
      structured `{ok:false,error}` for agent repair.
- [x] `tiresias/mcp_client.py`: agent speaks **real MCP** over an in-memory transport
      (no subprocess). 4 end-to-end MCP tests green (tool success, structured rejection,
      both resources).

### P0.5 — Agent (LangGraph `plan → execute → abstain`)
- [x] `tiresias/provider.py`: Anthropic provider shim (`LLMProvider` protocol; Bedrock
      later). Model `claude-opus-4-8`, adaptive thinking, structured-output planning via
      `messages.parse`, `stop_reason=="refusal"` → abstain.
- [x] `tiresias/agent.py`: LangGraph `retrieve → plan(draft|abstain) → execute →
      synthesize`, with a first-class **abstain** terminal reachable from retrieve
      (ungrounded), plan (declined), and execute (validation fails after 1 repair).
- [x] Agent executes SQL through the **real MCP** `run_validated_sql` tool and reads
      grounding from the MCP catalog/metric resources. Retrieval provides the grounded gate.
- [x] Output contract `TiresiasAnswer{question, answer, sql, citations, abstained, trace}`.
      5 graph-routing tests green (answer / OOD-abstain / planner-abstain / repair / exhausted).
      ty + ruff clean.

### P0.6 — Eval harness (~15 cases, pytest)
- [x] `tiresias/evals/gold.yaml`: 15 cases — 10 answerable restaurant questions +
      5 unanswerable (out-of-domain, no-such-column, ambiguous), each with expected
      behavior (`answer` + `must_reference` tables, or `abstain`).
- [x] `tiresias/evals/test_evals.py`: runs the real agent; deterministic checks
      (not-abstained + SQL ran + expected table cited; or correctly abstained).
      Marked `eval`+`slow`; **skips hermetically** without `ANTHROPIC_API_KEY` so CI
      stays green. LLM-judge deferred to Phase 4.
- [x] `uv run pytest tiresias/evals -m eval` — **15/15 green live** (Opus 4.8). One
      recalibration: retrieval grounding threshold 0.62 → **0.55** after the gold set
      showed in-domain/subtle-OOD overlap ("average tip per waiter" scores like a real
      restaurant question). Retrieval is now a lenient pre-filter; the planner is the
      authoritative abstain decider for borderline scores.

### P0.7 — Front door (interim Streamlit chat)
- [x] `views/tiresias.py`: chat page — answer + SQL + citations + trace; degrades
      gracefully (info + stop) when no key. Heavy imports lazy so other pages unaffected.
      AppTest smoke green.
- [x] Wired into `streamlit_app.py` navigation ("🔮 Ask Tiresias").

### P0.8 — Ship
- [x] Deploy-prep: mirrored new deps into `requirements.txt` (Railway pip path);
      Dockerfile now runs `dbt docs generate` so `catalog.json` exists at runtime.
- [x] `ANTHROPIC_API_KEY` set as a Railway service variable (confirmed live — the page
      loads the agent, no missing-key notice).
- [x] Deployed via Railway (`railway up`); merged to main. Page public at
      `elvis-production-e07a.up.railway.app` → "🔮 Ask Tiresias".
- [x] **Acceptance (LIVE, verified in browser):** restaurant question →
      cited SQL-backed answer over real data (top-5 failure rates w/ the governed
      metric) ✓; out-of-domain (crime) → clean abstention, no SQL, no guess ✓.
      Landing page healthy (Business Licenses KPI now shows Henderson count) ✓.
      Local `-m eval` 15/15 ✓.

**✅ PHASE 0 SHIPPED.** A stranger can ask a restaurant-inspection question and get a
cited, SQL-backed answer live; out-of-domain yields a clean abstention. MCP authoring,
RAG, LangGraph, and an eval harness — in miniature but real, deployed, and linkable.

## P0.9 — Abuse hardening (public endpoint)
- SQL boundary audited against 17 hostile inputs — all blocked: file reads
  (`read_text('/proc/self/environ')`, `read_csv`, `glob`, `read_blob`), metadata
  (`duckdb_settings()`, `pragma_table_info`, `information_schema`), alias-spoof of a
  file-read fn as an allowed table, UNION-to-function, multi-statement, ATTACH/DDL/DML.
  The read-only connection + SELECT-only + table allowlist + EXPLAIN + row cap hold.
- [x] App-side guards in `views/tiresias.py`: input-length cap, per-session cap, and a
      process-wide daily circuit breaker (all env-overridable: `TIRESIAS_MAX_*`).
      Safe error handling (no tracebacks leak to the public UI).
- [ ] **Hard backstop (Evan, Anthropic Console):** set a workspace **spend limit +
      budget alert**, and use a **dedicated, scoped API key** for this app so it can be
      rotated/killed independently. This is the ceiling nothing client-side can bypass.
- [ ] Optional: edge IP rate-limiting (Cloudflare/Railway) if bot traffic appears.

---

## Phase 1 — harden Elvis to production dbt + metric registry + Snowflake dual-target

Each of the three workstreams below is independently claimable. Start with the
Phase-0 domain (restaurant marts), expand outward.

### P1.1 — dbt contracts + tests + docs (restaurant domain first)
- [x] **Contracts enforced** on the 4 restaurant marts (`mart_restaurants`,
      `mart_inspections_over_time`, `mart_inspection_violations`, `mart_top_violations`)
      — every column declared with its exact `data_type` (incl. `hugeint`/`timestamp`),
      `contract: enforced: true`. Full column **docs** on all 4. Key **tests**
      (not_null/unique). `dbt build` green (PASS=14, WARN=0, ERROR=0); Tiresias's
      grounding gets the richer descriptions for free (43 tests still green).
- [x] Expanded **contracts** to all 28 enabled marts — every column declared at its
      exact warehouse `data_type`, `contract: enforced: true`. Existing tests + docs
      preserved. `dbt build` green (PASS=99, WARN=0, ERROR=0). *(Per-column doc
      enrichment for the previously-undocumented non-restaurant columns is a separate,
      lower-priority content pass; contracts now cover 100% of columns, docs remain
      partial for non-Tiresias marts.)*

### P1.2 — Full metric registry
- [x] Expanded `tiresias/metrics.yml` to 4 governed metrics: `restaurant_failure_rate`,
      `restaurant_compliance_rate`, `restaurant_avg_demerits`, `top_violation_frequency`
      — each grounded in a real mart column (arithmetic verbatim from the marts). New
      metrics flow automatically into the MCP metric resource, retrieval corpus, and
      agent grounding. Added a **registry-integrity test**: every metric's
      `source_table.source_column` and every `references` entry must resolve in the
      catalog (44 tests green).
- [ ] (Stretch, per PRD Open decision #2) evaluate MetricFlow / dbt Semantic Layer.

### P1.3 — Snowflake dual-target (folds in RECRUITER-PRIMER P3)
- [ ] Add a `snow` target to `profiles.yml`; guard DuckDB-specific SQL with
      `{{ target.type }}` / macros; `dbt parse --target snow` succeeds.
- [ ] Write `docs/SNOWFLAKE.md`. Keep `dev`/DuckDB the default.

**Acceptance:** clean dbt project, green CI, browsable metric catalog; `dbt parse
--target snow` succeeds and DuckDB-specific SQL is guarded/documented.

---

## Phase 2 — deepen the MCP server + RAG

### P2.1 — Hybrid retrieval (BM25 + dense)
- [x] `tiresias/retrieval.py`: added lexical **BM25** (`rank_bm25`) fused with the
      dense embeddings via **Reciprocal Rank Fusion** (RRF_K=60). Dense catches
      semantic paraphrase; BM25 catches exact column/table tokens. The abstain gate
      (`is_grounded`) stays on the calibrated dense cosine (`grounding_score`), so the
      gold-eval abstain behavior is unchanged; hybrid only improves context *ranking*.
      7 retrieval tests green (incl. real fastembed).

### P2.2 — Retrieval-quality mini-eval
- [x] `tiresias/evals/retrieval_gold.yaml` + `tests/test_retrieval_quality.py`:
      recall@k over labeled query→table/metric pairs, no LLM. **recall@3 = 1.00 (8/8)**
      with real fastembed. A retrieval regression now turns red deterministically.

### P2.3 — Deepen the MCP tool surface
- [ ] Add `list_tables`, `profile_column`, `get_metric` tools alongside
      `run_validated_sql` (full Phase-2 surface); tests over the client.

### P2.4 — Prove the server from Claude Code (manual)
- [ ] Screencast: Claude Code querying the warehouse through the Tiresias MCP server
      (stdio). *(Evan — manual demo; the stdio entrypoint `python -m tiresias.mcp_server`
      already exists.)*

## Deferred to later phases (not Phase 0)
- CI eval-regression gate + restaurant-mart seeds/contracts → Phase 1/Phase 4 (PRD).
  (CI is untouched in Phase 0; the tiresias tests need the warehouse, which CI lacks
  until restaurant fixtures are seeded.)

---

## Open decision needing a call before P0.0 completes

- **Embedding model** (distinct from the vector-*store* decision, which is settled as
  DuckDB-native for P0). To do honest "dense retrieval" we need vectors:
  - **`fastembed`** (ONNX, lightweight, no torch) — real dense embeddings, small image,
    vendor-neutral, deployable on the existing Railway build. *Recommended for P0.*
  - **Voyage AI API** — no local model weight but adds a second API key + query-time
    network dependency.
  - **`sentence-transformers`** — most "standard" but pulls torch (heavy Docker image).
