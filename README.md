# Tiresias

A grounded text-to-SQL agent for dbt + DuckDB warehouses. Ask a question in plain
English; Tiresias retrieves the real schema and governed metrics, drafts one
read-only query, validates it against the live catalog, runs it through an MCP
tool it can only use read-only, and answers **with the SQL and citations shown**.
When it can't ground the answer in the warehouse, it **abstains** instead of
guessing.

Tiresias is the blind seer of Thebes, who speaks only what he can truly see.

## How it works

```
retrieve → (grounded?) → plan → (query?) → execute → (ok?) → synthesize
                │                  │                   │
                └──────────────────┴───────────────────┴──▶ abstain
```

- **Retrieval:** hybrid dense (fastembed, local ONNX) + BM25, fused with RRF, over
  the allowlisted tables, the metric registry, and the city's example questions.
  A calibrated dense-score threshold screens out clearly off-topic questions.
- **Planning:** Claude drafts one SELECT or abstains (structured output).
- **Execution:** a sqlglot guard (single SELECT, table/schema allowlist, map-only
  columns rejected, row cap, EXPLAIN against the live catalog), a read-only DuckDB
  connection, a statement timeout, and a result-size cap.
- **MCP:** the same server backs the agent (in-memory) and external clients such as
  Claude Code (stdio).

## Use it in a city app

```toml
# pyproject.toml
dependencies = ["tiresias[streamlit] @ git+https://github.com/EvanWAppel/tiresias@v0.1.0"]
```

Describe the warehouse in a `tiresias.yml` at the repo root. Paths are relative
to the file. See [`examples/elvis/tiresias.yml`](examples/elvis/tiresias.yml) for
a full one; the minimum is:

```yaml
city: Springfield
blurb: restaurant inspections, service calls, and parks
warehouse: springfield.duckdb
dbt_target: target          # holds catalog.json + manifest.json (dbt docs generate)
metrics: metrics.yml        # governed metric registry
tables:
  allowed: [mart_restaurants, mart_service_calls]
```

Then add a page:

```python
from pathlib import Path
from tiresias.chat import render_chat
from tiresias.config import load_config

render_chat(load_config(Path("tiresias.yml")))
```

A public page needs `ANTHROPIC_API_KEY` from a **dedicated, scoped,
spend-capped key for that app**, never a personal one. The chat's own caps
(question length, per session, per day) come from `limits:` and can be
overridden with `TIRESIAS_MAX_*` environment variables.

## Command line

```
tiresias check     --config tiresias.yml   config vs dbt artifacts (missing tables, undocumented columns)
tiresias calibrate --config tiresias.yml   grounding score of every gold question, to pick the threshold
tiresias eval      --config tiresias.yml   retrieval recall@k, then the live gold set (needs a key)
tiresias mcp       --config tiresias.yml   stdio MCP server
```

To use it from Claude Code: `claude mcp add tiresias -- uv run tiresias mcp --config tiresias.yml`.

## Development

```
uv sync --all-extras
uv run pytest -m "not slow"   # hermetic: builds a synthetic city in a temp dir
uv run ruff check tiresias tests && uv run ty check tiresias tests
```

The suite needs no warehouse, network, or API key. `-m slow` adds the real
fastembed model. Planning docs: [`PRD.md`](PRD.md), [`TASKS.md`](TASKS.md),
[`DECISIONS.md`](DECISIONS.md).
