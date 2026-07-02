# Changelog

All notable changes to `tuskledger-mcp` will be documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-06-13

Six research-layer tools (17 → 23) wrapping the backend's new
`/api/research/*` endpoints — the long-term-hold research layer:

- `get_position_research` — held securities × research overlay (the cockpit).
- `get_research_entities` — the scored universe, filterable by tier /
  min conviction / held-only.
- `get_research_for_ticker` — full dossier (thesis, catalysts, risks,
  invalidation triggers, sources) for one ticker.
- `get_research_alerts` — stale / overdue-catalyst / invalidation-watch /
  below-cost-large-position / concentration flags.
- `upsert_research_entity`, `update_research_field` — schema-validated
  writes (blocked on read-only devices + the public demo by the backend).

`domain` is optional on the read/write tools — omit it and the only/first
research file on disk is used. Publishing (uv build/publish + the
tool-count bump on the site + marketplace) is left as a manual step.

## [0.2.0] — 2026-06-11

Four new read-only tools (13 → 17), all wrapping endpoints the backend
already served — the client methods existed, they were just never
exposed to assistants:

- `get_budget` — per-category budget limits for a month (or all
  budgets). Limits only; the description tells the assistant to pair
  it with `get_spending_summary` to compute over/under.
- `get_cash_flow_forecast` — day-by-day projection (7–180 days) with
  running balance, projected low point, and the recurring events that
  drive it. Baseline selectable (median_3 / median_6 / last_month /
  rolling_90).
- `get_trading_tax_summary` — realized gains for a year: FIFO lot
  matching, chain-correct wash-sale adjustments, ST/LT split,
  estimated tax at configurable rates.
- `get_merchant_details` — single-merchant deep-dive: YTD, all-time,
  12-month trend, recent transactions; normalized-name matching.

## [0.1.1] — 2026-05-04

Honest contract pass for `get_retirement_projection`. The v0.1.0
tool advertised "uses your saved scenario" and took zero params,
but scenarios live in browser localStorage, not the backend — so
every call 422'd on missing `current_age`. Two paths considered
(server-side scenario persistence vs. accept params at the tool):
went with the latter because it ships in 15 min and doesn't break
the UI's single-source-of-truth for scenario state.

### Changed
- `get_retirement_projection` now requires `current_age` and accepts
  the most useful optional params (retirement_age,
  desired_annual_income, annual_contribution, return_rate,
  withdrawal_rate, pension/SS basics, inflation_rate). Description
  updated to drop the inaccurate "saved scenario" claim and explain
  how to get scenario values into the assistant's prompt.
- Both other tools whose backend contracts had drifted are also
  fully usable now thanks to companion fixes in the main `tuskledger`
  repo: `get_spending_summary` and `get_top_merchants` both now
  accept `start_date`/`end_date` end-to-end.

## [0.1.0] — 2026-04-30

Initial release. Extracted from the main
[`tuskledger`](https://github.com/BradMorphsters/tuskledger) repo into
its own package + repo so it can version, ship, and be discovered
independently of the main app.

### Added
- Stdio MCP server (`tuskledger-mcp` console script).
- Thirteen read-mostly tools covering accounts, transactions
  (filtered + free-text search), spending summary, top merchants,
  recurring subscriptions, upcoming bills, net worth, holdings,
  investments summary, retirement projection, and triggering a
  Plaid sync.
- Synchronous HTTP client for the Tusk Ledger backend with friendly
  error translation (`TuskLedgerError`).
- Configuration via `TUSKLEDGER_BASE_URL` and
  `TUSKLEDGER_TIMEOUT_SECONDS` env vars.
- Unit tests covering the dispatch layer and tool-surface invariants
  (each tool has a dispatch branch; descriptions are substantive
  enough for LLM tool selection).
- GitHub Actions CI: pytest on Python 3.10/3.11/3.12.

### Notes
- v0 is read-mostly. No destructive operations exposed (no delete,
  no schema mutation, no auth disable, no token rotation). The bar
  for adding write tools stays high — irreversible changes belong
  in the web UI.
- Auth assumption: backend running with `DEV_BYPASS_AUTH=true`
  (the common single-machine pattern). Auth-aware support is on the
  roadmap.
