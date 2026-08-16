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
- [ ] Set `ANTHROPIC_API_KEY` as a Railway service variable (reaches runtime). *(needs Evan)*
- [ ] Deploy via existing Railway/Docker path; confirm the page is public & linkable.
      *(outward action — needs Evan's say-so)*
- [x] **Acceptance (local):** live cited answers for restaurant questions ✓; clean
      abstention for out-of-domain ✓; `-m eval` 15/15 ✓. Remaining: deploy + public link.

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
