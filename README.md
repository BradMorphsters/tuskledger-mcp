# tuskledger-mcp

> **Model Context Protocol server for [Tusk Ledger](https://www.tuskledger.com).**
> Gives your AI assistant typed access to your local personal finance
> data — without sending anything outside your machine.

[![CI](https://github.com/BradMorphsters/tuskledger-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/BradMorphsters/tuskledger-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)
[![Local-first](https://img.shields.io/badge/local--first-yes-brightgreen.svg)](https://www.tuskledger.com#architecture)
[![Tools: 13](https://img.shields.io/badge/tools-13-1185fe.svg)](#what-tools-are-available)
[![Main app](https://img.shields.io/badge/main%20app-tuskledger-1185fe.svg)](https://github.com/BradMorphsters/tuskledger)

---

## Quick context

[**Tusk Ledger**](https://www.tuskledger.com) is a self-hosted,
Mint-style personal finance app that pulls your accounts via Plaid
and runs entirely on your laptop. **This package** (`tuskledger-mcp`)
is the bridge that lets an AI assistant — Claude Desktop, Cursor,
Cowork, Claude Code, anything that speaks
[MCP](https://modelcontextprotocol.io) — read that data and answer
questions about your finances using typed tool calls instead of
scraping the React UI.

## What you can ask your assistant

Once the server is wired up, these all work in plain English:

- *"Categorize the last 6 months of transactions from Whole Foods as
  Groceries instead of Shopping."* → Assistant queries them, you
  confirm, then makes a rule.
- *"What did I spend on coffee last quarter?"* → 3 seconds, no UI clicks.
- *"My net worth dropped this morning — what's causing it?"* →
  Assistant pulls accounts, balances, and recent transactions and
  diagnoses.
- *"Am I on track to max out my HSA this year?"* → Reads HSA bucket +
  YTD contributions + IRS limit, returns the gap.
- *"What subscriptions am I paying for that I haven't used recently?"*
  → Lists recurring charges with cadence and last-paid date.
- *"Will my checking dip below $1k before payday?"* → Pulls upcoming
  bills + paychecks and projects a running balance.

**Local-first, no exceptions.** The server talks only to your
Tusk Ledger backend on `http://127.0.0.1:8000`. There is no "MCP
cloud" — this is one Python process on your machine, talking to
another Python process on the same machine. Your transactions never
leave the laptop.

## What tools are available

13 read-mostly tools. Group at a glance:

| Group | Tools |
|---|---|
| **Accounts** | `list_accounts`, `list_stale_accounts` |
| **Transactions** | `query_transactions`, `search_transactions` |
| **Spending insight** | `get_spending_summary`, `get_top_merchants`, `get_recurring_subscriptions` |
| **Cash flow** | `get_upcoming_bills` |
| **Net worth & investments** | `get_net_worth`, `get_holdings`, `get_investments_summary` |
| **Planning** | `get_retirement_projection` (Monte Carlo) |
| **Ops** | `run_sync` (trigger a Plaid pull) |

Full schemas (parameters, defaults, examples) are reported by the
server itself — your MCP client renders them, and they're also
visible in [`tuskledger_mcp/server.py`](tuskledger_mcp/server.py).

## Prerequisites

- A running [Tusk Ledger](https://github.com/BradMorphsters/tuskledger)
  install (the main app), reachable on `http://127.0.0.1:8000`
- The backend started with `DEV_BYPASS_AUTH=true` — **v0 of the MCP
  server is auth-bypass-only.** If you leave auth on you'll get 401
  on every tool call. See [Auth](#auth) below for the rationale and
  the auth-aware roadmap.
- Python 3.10+
- An MCP-aware client (Claude Desktop, Cursor, Cowork, Claude Code, …)

## Install

> **A note for users coming from MCP marketplace listings (LobeHub, Glama,
> mcp.so, etc.):** these directories try to auto-install MCP servers in a
> sandbox to verify they boot. This server intentionally won't pass that
> check, because it requires the main Tusk Ledger app already running on
> your machine. The "cannot be installed" / red badges on those listings
> are about the auto-installer, not about this package. Use one of the
> manual config snippets below.

### Option A — `uvx` (recommended; no permanent install)

If you have [uv](https://docs.astral.sh/uv/) (`pip install uv`):

```jsonc
// In your MCP client's config
{
  "mcpServers": {
    "tuskledger": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/BradMorphsters/tuskledger-mcp", "tuskledger-mcp"]
    }
  }
}
```

`uvx` handles the isolated Python env; nothing pollutes your global
Python. The server is fetched and cached on first invocation.

### Option B — `pip install` from GitHub

```bash
pip install git+https://github.com/BradMorphsters/tuskledger-mcp
```

Then point your MCP client at the installed `tuskledger-mcp` binary:

```jsonc
{
  "mcpServers": {
    "tuskledger": {
      "command": "tuskledger-mcp"
    }
  }
}
```

(Use the full path from `which tuskledger-mcp` if you're using a venv.)

### Option C — clone for development

```bash
git clone https://github.com/BradMorphsters/tuskledger-mcp
cd tuskledger-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Where MCP client configs live

| Client | Config path |
|---|---|
| **Claude Desktop** (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Claude Desktop** (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| **Cursor** | Settings → Features → Model Context Protocol → paste the same `mcpServers` JSON shown above |
| **Cowork** | Same `mcpServers` JSON as Claude Desktop. Add it via Cowork's MCP server settings (or, if you're managing it as a plugin, ship the snippet inside the plugin's `.mcp.json`). [Anthropic MCP docs](https://docs.claude.com/en/docs/claude-code/mcp) |
| **Claude Code** | Project-level `.claude/mcp.json`, or user-level via `claude mcp add tuskledger uvx --from git+https://github.com/BradMorphsters/tuskledger-mcp tuskledger-mcp` |

After editing the config, restart the client. The server boots when
the client starts and shuts down when it closes.

## Configuration

Two environment variables, both optional:

| Var | Default | Notes |
|---|---|---|
| `TUSKLEDGER_BASE_URL` | `http://127.0.0.1:8000` | Where your Tusk Ledger backend listens. Override if you've moved the port. |
| `TUSKLEDGER_TIMEOUT_SECONDS` | `10` | Per-request timeout. Bump if your DB is huge and a query takes a while. |

Example:

```jsonc
{
  "mcpServers": {
    "tuskledger": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/BradMorphsters/tuskledger-mcp", "tuskledger-mcp"],
      "env": {
        "TUSKLEDGER_BASE_URL": "http://127.0.0.1:8000",
        "TUSKLEDGER_TIMEOUT_SECONDS": "30"
      }
    }
  }
}
```

## Auth

This v0 assumes your Tusk Ledger backend is running with
`DEV_BYPASS_AUTH=true` (the common single-machine pattern documented
in the main repo's README). If you've kept auth enabled, the MCP
server's calls will fail with 401s and you'll see the error in your
assistant's response.

Auth-aware support is on the roadmap. Until then, if you want both
auth and MCP, run the backend with `DEV_BYPASS_AUTH=true` *only* when
you're using the assistant, and flip it back when you're done.

## What this server intentionally does NOT do

By design, v0 is **read-mostly**. The server doesn't expose:

- Deleting accounts, transactions, rules, or goals
- Modifying the database schema or running migrations
- Disabling auth or rotating the encryption key
- Touching Plaid access tokens
- Sending data anywhere outside `127.0.0.1`

The reasoning: an AI assistant should be able to help you understand
your data and run safe operations (sync, queries), but irreversible
changes belong in the web UI where you can see what's about to
happen. We may add structured write tools (e.g. "create a rule") in
later versions with explicit confirmation flows, but the bar will
stay high.

## Troubleshooting

**`Could not reach Tusk Ledger backend at http://127.0.0.1:8000`** —
Your Tusk Ledger app isn't running. From the main repo: `./start.sh`.

**`401 Unauthorized` from any tool** — Auth is on. See the Auth
section above. Run with `DEV_BYPASS_AUTH=true` for now.

**`404 Not Found`** — The backend doesn't have the endpoint we're
trying to hit. Probably means you're on an older version of Tusk
Ledger. Update the main app, restart your MCP client.

**Tools don't appear in your assistant** — The MCP server failed to
boot. Check your client's MCP server logs (Claude Desktop has a "View
MCP server logs" menu item). Common causes: bad path in the config,
Python not on PATH, `uvx` not installed.

**General health check** — From the main Tusk Ledger repo:
`./tuskledger doctor`. This is the canonical diagnostic for the whole
install.

## Development

```bash
git clone https://github.com/BradMorphsters/tuskledger-mcp
cd tuskledger-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install pytest pytest-asyncio
pytest tests/ -v
```

The tests don't bring up an MCP transport — they exercise the
dispatch layer directly with a mock client. The MCP protocol itself
is just a wrapper.

CI runs the same suite on Python 3.10/3.11/3.12 via GitHub Actions
(see `.github/workflows/ci.yml`).

## Project links

- Main app: https://github.com/BradMorphsters/tuskledger
- Project site: https://www.tuskledger.com
- For agents browsing externally: https://www.tuskledger.com/llms.txt
- Issues / discussions: https://github.com/BradMorphsters/tuskledger-mcp/issues
- License: [MIT](LICENSE)
