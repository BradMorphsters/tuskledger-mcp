# Changelog

All notable changes to `tuskledger-mcp` will be documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
