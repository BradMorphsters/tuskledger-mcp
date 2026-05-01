# AGENTS.md

> Working memory for AI assistants (Claude Code, Cursor, Cowork, etc.)
> operating on this repository. Read this first.

## What this project is

`tuskledger-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io)
server that runs locally on a user's machine and gives their AI
assistant typed access to data in their
[Tusk Ledger](https://www.tuskledger.com) install. It's a thin
adapter — the actual finance data and logic live in the main
[`tuskledger`](https://github.com/BradMorphsters/tuskledger) app; this
package just translates MCP tool calls into HTTP requests against
that app's local FastAPI backend (`http://127.0.0.1:8000` by default).

**Local-first, no exceptions.** Nothing here calls out to the network.
The only HTTP destination is `127.0.0.1`. If you find yourself
writing a request to a non-localhost URL, stop and ask the user.

## Permission boundaries

### Safe to do without asking
- Add a new tool that wraps an existing read-only backend endpoint
- Improve a tool description (LLM tool-selection accuracy depends on these)
- Tighten input schemas (`additionalProperties: false`, required fields, etc.)
- Add tests
- Update the README, CHANGELOG, or AGENTS.md

### Ask the user first
- Add a tool that performs a write/mutation
- Bump the `mcp` SDK version
- Change the JSON shape of any tool's output (it's a contract for the LLM caller)
- Change the env-var names (users have these wired in their MCP client config)

### Never do without explicit user instruction
- Add a tool that performs a destructive operation (delete a transaction,
  remove a connected account, rotate keys, etc.)
- Add a non-localhost HTTP destination
- Capture, log, or transmit Plaid tokens, balances, or transaction details
  outside the user's machine
- Change the package name (it's published as `tuskledger-mcp`)

## Repo structure

```
tuskledger-mcp/
├── README.md            ← user-facing install + usage docs
├── AGENTS.md            ← you are here
├── CHANGELOG.md
├── LICENSE              ← MIT
├── pyproject.toml       ← package metadata, deps, console script
├── tuskledger_mcp/
│   ├── __init__.py      ← __version__
│   ├── __main__.py      ← `python -m tuskledger_mcp` entry
│   ├── client.py        ← TuskLedgerClient: sync httpx wrapper
│   └── server.py        ← TOOLS list + _dispatch + build_server + serve_stdio
└── tests/
    └── test_server.py   ← dispatch + schema invariants
```

## Conventions

- **Tools list = source of truth.** `TOOLS` in `server.py` is the
  canonical surface. Adding a tool means: new `Tool(...)` entry,
  matching `_dispatch` branch, matching client method, matching test
  in `test_every_tool_has_a_dispatch_branch`.
- **Descriptions matter more than names.** LLMs pick tools by reading
  descriptions. Two-sentence descriptions beat one-word names every
  time. There's a test that enforces a 50-char floor.
- **Inputs use `additionalProperties: false`.** Strict input
  validation catches typos before they become bad calls. Don't
  loosen this.
- **Errors are structured, not raised.** A backend failure becomes a
  `TextContent` payload with `error: true` so the assistant can show
  it to the user. Raising would tear down the whole MCP session.
- **Sync client + async dispatch.** Each tool call wraps a sync HTTP
  call in `asyncio.to_thread()`. Linear, readable, fast on localhost.

## Common operations

### Run the tests

```bash
pip install -e ".[test]"   # or: pip install -e . pytest pytest-asyncio
pytest tests/ -v
```

### Run the server locally (stdio)

```bash
pip install -e .
tuskledger-mcp
```

It will block waiting on stdio. Connect an MCP client to verify; the
README has Claude Desktop / Cursor / Cowork / Claude Code config
examples.

### Add a new tool

1. Add the corresponding method on `TuskLedgerClient` in `client.py`
2. Add a `Tool(...)` entry to `TOOLS` in `server.py` (substantive
   description; strict input schema)
3. Add a branch to `_dispatch` mapping the tool name to the client call
4. Add a test (the auto-coverage check verifies you didn't forget the
   dispatch branch)
5. Update `CHANGELOG.md` under "Unreleased"

### Bump the version

1. `tuskledger_mcp/__init__.py` → `__version__`
2. `pyproject.toml` → `version`
3. `CHANGELOG.md` → cut a new section
4. Tag: `git tag v0.x.0 && git push --tags`

## Project links

- Main app: https://github.com/BradMorphsters/tuskledger
- This repo: https://github.com/BradMorphsters/tuskledger-mcp
- Site: https://www.tuskledger.com
- For LLMs browsing externally: https://www.tuskledger.com/llms.txt
