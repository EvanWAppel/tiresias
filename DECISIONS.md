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
