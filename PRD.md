# Tiresias — Product Requirements

**Tiresias** is a grounded text-to-SQL agent for dbt + DuckDB warehouses. You ask a
natural-language question, and it retrieves the real schema and governed metrics,
drafts one read-only query, validates it against the live catalog, executes it
through an MCP tool it can only use read-only, and answers **with the SQL and
citations shown**. When it can't ground the answer in the warehouse, it **abstains**
instead of guessing.

The name is the point: Tiresias is the blind seer of Thebes, who speaks only what
he can truly see. This agent says only what it can trace to a real row, and its
eval harness measures exactly that: grounded accuracy *and* correct refusal.

## Why a standalone repo

Tiresias was built inside [Elvis](https://github.com/EvanWAppel/elvis) (Las Vegas
open data) across Phases 0–3; that history is preserved here. Three sibling city
apps share Elvis's stack (dbt on DuckDB, Streamlit, Railway): robbins (Seattle),
gregan (Glendora) and groening (Portland). Extracting the engine lets every city
install one tested, versioned copy instead of forking it.

## Decisions (interview, 2026-10-04)

| Topic | Decision | Rejected |
|---|---|---|
| Shape | **Library** that each city app installs and pins | One shared service querying every city's warehouse (warehouses would have to be shipped to it; single point of failure) |
| City config | **`tiresias.yml`** in each city repo, validated by Pydantic | A Python settings module (logic creeps into config) |
| Chat UI | **Optional extra** `tiresias[streamlit]` providing `render_chat(config)`, including the abuse guards | Each city keeping its own page and guards |
| History | **Preserved** via `git filter-repo` from Elvis | Fresh start |
| Visibility | **Public**, standard branch protection | Private (city deploys would need a token) |
| Docs | Planning docs move here; Elvis keeps a pointer | Copies in both repos |

## What lives where

**This repo (the engine):** SQL guard; catalog loader (dbt `manifest.json` +
`catalog.json`); hybrid retrieval (fastembed + BM25 with RRF); LangGraph agent;
provider shim (Anthropic, Bedrock later); MCP server and in-memory client;
statement timeout and result-size cap; eval runner and threshold calibration;
the optional Streamlit chat.

**Each city repo (its config):** its warehouse and dbt artifacts, plus
`tiresias.yml` with:
- city name and a one-line domain blurb (used in prompts and the abstain message)
- warehouse path and dbt `target/` path
- allowed / excluded tables and map-only columns
- retrieval examples (question, guidance, grounding tables)
- path to its metric registry
- paths to its gold sets
- grounding threshold, plus the calibration notes behind it
- limits (row cap, timeout, result bytes, abuse caps)

## Requirements

1. **No city specifics in the engine.** No table names, city names or example
   questions in `tiresias/`; everything comes from `tiresias.yml`. A test
   scans the package for city strings.
2. **Hermetic tests.** A small synthetic DuckDB warehouse plus minimal dbt
   artifacts, built in `conftest.py`, so CI runs with no real warehouse, no
   network, and no API key. The live eval stays opt-in and city-side.
3. **Behavior preserved.** All existing guard, timeout, map-only-column,
   retrieval, agent-routing and MCP tests pass against the fixture. Elvis's live
   gold set still passes 36/36 after Elvis switches to the library.
4. **CLI entry points:** `tiresias mcp --config` (stdio MCP server, for Claude
   Code), `tiresias eval --config` (gold set), and `tiresias calibrate --config`
   (grounding-score report for picking the threshold).
5. **Versioned releases.** Git tags (`v0.1.0`, …); cities pin a tag, e.g.
   `tiresias[streamlit] @ git+https://github.com/EvanWAppel/tiresias@v0.1.0`.
6. **Python 3.12** (`>=3.12,<3.13`), matching the city apps and the onnxruntime
   wheels for Intel Macs.
7. **Tooling:** uv, ruff, ty, pytest, prek; ROCRLL; `BLOCKED.md` and `DECISIONS.md`.

## Guardrails (carried over)

- Abstain-first: refusing is tested behavior, not an error path.
- Read-only everywhere: read-only connection, SELECT-only guard, table and
  column allowlists, row cap, timeout, result-size cap.
- Public endpoints use a **dedicated, scoped, spend-capped API key per app**,
  never a personal one. The engine never reads keys itself beyond the SDK's
  environment variable.
- The agent never sees raw data; humans inspect data.

## Phase plan

- **E0 — Extract:** history split, new repo, branch protection. This PRD and
  TASKS.md.
- **E1 — Config-driven engine:** `tiresias.yml` schema; remove Elvis specifics;
  prompts parameterized.
- **E2 — Hermetic tests + CI:** synthetic fixture warehouse; CI runs ruff, ty and
  pytest.
- **E3 — Packaging + CLI + Streamlit extra:** `pyproject.toml`, entry points,
  `render_chat`; tag `v0.1.0`.
- **E4 — Elvis adopts v0.1.0:** Elvis deletes its `tiresias/` copy, adds
  `tiresias.yml` and its examples, metrics and gold sets; live eval 36/36;
  deploy.
- **E5 — Siblings:** robbins, then gregan, then groening (each: docs first,
  config, calibration, live eval). Separate PRs per city.

## Open questions

- robbins already has its own text-to-SQL (`nl_sql.py`): replace it or run
  alongside? Decide at E5.
