# Review — E3 CLI, eval harness, Streamlit chat (PR #2)

Reviewer: fresh-context same-model subagent (adversarial), 2026-10-04.
Scope: `git diff e1-config-engine..e3-packaging`. **No HIGH findings.** Public-chat
guards probed with AppTest: check order (session → length → daily → count → model
call), exceptions counted and never shown, `st.stop()` not swallowed, daily limiter
shared and lock-guarded. MCP stdio writes only JSON-RPC to stdout.

| # | Sev | Finding | Disposition |
|---|-----|---------|-------------|
| 1 | MED | Agent cached by city name only: an edited `tiresias.yml` kept serving the old allowlist/threshold (confirmed) | **Fixed**: cache keyed on the full config JSON; AppTest |
| 2 | MED | "Could not run" errors exited 1, same as a failed check | **Fixed**: logged traceback, exit 2; test |
| 3 | MED | `run_gold` aborted the whole set on one agent exception | **Fixed**: recorded as a failed case, run continues; test |
| 4 | LOW | `eval --retrieval-only` with no retrieval gold passed silently | **Fixed**: exit 2; test |
| 5 | LOW | Daily limiter re-created (count reset) when the cap changed mid-day | **Fixed**: one limiter per city, cap updated in place |
| 6 | LOW | Trace expander shows guard/DuckDB rejection text to the public | Open (pre-existing on the old page) — Evan's call: keep (transparency) or hide on public pages |
| 7 | LOW | Bad `TIRESIAS_MAX_*` breaks every load (fails closed) | Accepted; same as before |
| 8 | LOW | Retrieval gold not range-checked; duplicate gold ids | **Fixed**: k ≥ 1, 0 ≤ min_recall ≤ 1, ≥ 1 case, unique ids; tests |
| 9 | LOW | Whitespace-only question after the cap returns silently | Accepted, harmless |

Fixing #1 also surfaced that the read-only map-only mapping (E1 review fix) did not
serialize to JSON; added a serializer and a test.
