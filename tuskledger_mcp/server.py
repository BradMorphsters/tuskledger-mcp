"""
The MCP server itself. Defines the tool surface and dispatches calls.

Design choices:
  - Read-mostly v0. We don't expose anything destructive (no
    delete-account, no rotate-encryption-key, no disable-auth) even
    though the backend supports those operations. The agent shouldn't
    be able to do irreversible damage without going through the web UI
    where the user can see what's happening.
  - One MCP tool per common question an assistant would actually ask:
    'what accounts are connected?', 'how much did I spend on coffee
    last month?', 'what's coming due in the next two weeks?'. Resist
    the urge to ship every endpoint as a tool — fewer, well-named
    tools beat a long list of grep-able ones.
  - Tool descriptions are prose, not just titles. The LLM picking
    which tool to call uses these descriptions; clear text here
    saves a lot of bad calls.
  - Inputs default to sensible scopes (e.g. transactions default to
    last 90 days) so a tool call without arguments still does
    something useful.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from . import __version__
from .client import TuskLedgerClient, TuskLedgerError


# Log to stderr so MCP's stdio transport (stdout-based) stays clean.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("tuskledger-mcp")


# ── Tool definitions ─────────────────────────────────────────────
# Each entry: (name, description, JSON Schema for input).
# Keep names lowercase_underscore; descriptions actionable + specific.

TOOLS: list[Tool] = [
    Tool(
        name="list_accounts",
        description=(
            "List every connected account in Tusk Ledger with current "
            "balance, type (checking, savings, credit, investment, loan), "
            "and last-sync timestamp. Use this first to understand what "
            "accounts exist before drilling into transactions or holdings."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="list_stale_accounts",
        description=(
            "Return accounts whose data is older than the freshness "
            "threshold (a week for synced accounts, a month for manual). "
            "Useful when the user asks 'why is my net worth wrong?' — "
            "stale balances are usually the cause."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="query_transactions",
        description=(
            "List transactions matching optional filters. Returns the most "
            "recent matches first. Common filter combos:\n"
            "  • account_id + start_date + end_date  → 'all transactions in "
            "    my checking account this month'\n"
            "  • category='Coffee' + start_date='2026-01-01'  → 'every "
            "    coffee purchase since New Year'\n"
            "Defaults to no filter (returns the most recent 100 transactions "
            "across all accounts)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "description": "Filter to a single account by id."},
                "category":   {"type": "string",  "description": "Filter to a single category name (exact match)."},
                "start_date": {"type": "string",  "description": "ISO date YYYY-MM-DD; inclusive lower bound."},
                "end_date":   {"type": "string",  "description": "ISO date YYYY-MM-DD; inclusive upper bound."},
                "limit":      {"type": "integer", "description": "Max rows to return (default 100, max 500)."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="search_transactions",
        description=(
            "Free-text search across transaction names, merchant names, and "
            "notes. Use when the user asks 'find that Whole Foods charge "
            "from last week' or 'when did I last pay Verizon?'. Different "
            "from query_transactions in that this is a fuzzy text search, "
            "not a structured filter."
        ),
        inputSchema={
            "type": "object",
            "required": ["q"],
            "properties": {
                "q":     {"type": "string",  "description": "Search string. Matches partial words, case-insensitive."},
                "limit": {"type": "integer", "description": "Max rows (default 50)."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_spending_summary",
        description=(
            "Aggregated spending totals broken down by category for a date "
            "range. Returns totals + per-category subtotals + counts. "
            "Defaults to the current calendar month if no dates given."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start_date":    {"type": "string", "description": "ISO date YYYY-MM-DD."},
                "end_date":      {"type": "string", "description": "ISO date YYYY-MM-DD."},
                "exclude_business": {"type": "boolean", "description": "Drop transactions tagged as business (default false)."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_top_merchants",
        description=(
            "Top N merchants by total spend in a date range. Returns merchant "
            "name, total amount, transaction count, and a sparkline of the "
            "monthly trend. Useful for 'who am I paying the most?'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string",  "description": "ISO date."},
                "end_date":   {"type": "string",  "description": "ISO date."},
                "limit":      {"type": "integer", "description": "How many merchants to return (default 10)."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_recurring_subscriptions",
        description=(
            "List detected recurring subscriptions: Netflix, Spotify, gym, "
            "etc. Returns merchant, cadence (monthly/annual/etc.), last "
            "amount, next expected date, and confidence. The user often "
            "asks 'what subscriptions do I have' — this answers it."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="get_upcoming_bills",
        description=(
            "Forward 30-day calendar of expected bills + paychecks with a "
            "running balance. Returns each event's date, amount, source "
            "(merchant or paycheck), and the projected account balance "
            "after that event. Useful for 'is my account going to dip "
            "before payday?'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days forward to look (default 30)."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_net_worth",
        description=(
            "Current net worth (assets minus liabilities) plus a 12-month "
            "trend. Numbers are point-in-time from the last sync, not "
            "live-computed. Use list_stale_accounts to verify freshness."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "history": {"type": "boolean", "description": "If true, return the full snapshot history instead of just latest."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_holdings",
        description=(
            "Current investment holdings across every connected brokerage "
            "and 401(k). Returns symbol, account, quantity, current value, "
            "and unrealized gain/loss per position."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="get_investments_summary",
        description=(
            "Roll-up of investment portfolio: total value, asset allocation "
            "(stocks/bonds/cash), top 5 holdings, % YTD gain. The 'how are "
            "my investments doing?' answer."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="get_retirement_projection",
        description=(
            "Run the multi-decade Monte Carlo retirement simulator. Returns "
            "probability of success, depletion age, and summary at key "
            "milestones (retirement, age 73 for RMDs, etc.).\n\n"
            "Caveat: scenarios live in the Tusk Ledger UI's localStorage on "
            "the device the user last edited from — they aren't accessible "
            "to this tool. So the user (or their assistant) must supply at "
            "least current_age. Other params accept sensible defaults that "
            "match the standard 4% rule scenario; pass any you know to "
            "tighten the projection. To pull a saved scenario verbatim, the "
            "user can copy it out of the Retirement page in the UI and "
            "paste the values into the assistant's prompt."
        ),
        inputSchema={
            "type": "object",
            "required": ["current_age"],
            "properties": {
                "current_age":           {"type": "integer", "description": "User's current age. Required."},
                "retirement_age":        {"type": "integer", "description": "Target retirement age (default 65)."},
                "spouse_age":            {"type": "integer", "description": "Spouse's current age. Optional — enables two-phase simulation when paired with spouse_retirement_age."},
                "spouse_retirement_age": {"type": "integer", "description": "Age at which the spouse retires (in spouse's years)."},
                "desired_annual_income": {"type": "number",  "description": "Target annual spending in retirement, today's dollars (default 80000)."},
                "annual_contribution":   {"type": "number",  "description": "Annual contribution. Omit to auto-detect from last 12mo of investment-account inflows."},
                "return_rate":           {"type": "number",  "description": "Real annual return during accumulation (default 0.06 = 6%)."},
                "withdrawal_rate":       {"type": "number",  "description": "Safe withdrawal rate (default 0.04 = the 4% rule)."},
                "pension_annual":        {"type": "number",  "description": "Annual pension income, today's dollars."},
                "ss_annual":             {"type": "number",  "description": "Annual Social Security at the user's claim age."},
                "ss_start_age":          {"type": "integer", "description": "Age at which to claim SS (62–70, default 67)."},
                "inflation_rate":        {"type": "number",  "description": "Long-run inflation assumption (default 0.025)."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_budget",
        description=(
            "Budget limits for a month: per-category limit_amount plus an "
            "optional total_limit. Omit month/year for a list of every "
            "budget that exists. NOTE: returns limits only, not spending — "
            "pair with get_spending_summary for the same month to compute "
            "over/under per category."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "month": {"type": "integer", "minimum": 1, "maximum": 12, "description": "1-12. Requires year."},
                "year": {"type": "integer", "minimum": 2000, "maximum": 2100, "description": "e.g. 2026. Requires month."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_cash_flow_forecast",
        description=(
            "Project the next N days of cash flow from recurring charges/"
            "income (known dates and amounts) plus a variable-spend "
            "baseline. Returns a day-by-day series with running balance, "
            "the projected low point, and upcoming events. The 'will I "
            "have enough cash before payday?' answer."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 7, "maximum": 180, "description": "Forecast horizon in days. Default 30."},
                "baseline": {
                    "type": "string",
                    "enum": ["median_3", "median_6", "last_month", "rolling_90"],
                    "description": "How variable (non-recurring) spend is estimated. Default median_3.",
                },
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_trading_tax_summary",
        description=(
            "Realized gains/losses for a calendar year: per-account FIFO "
            "lot matching mirroring the 1099-B, chain-correct wash-sale "
            "adjustments, short- vs long-term split, and estimated tax. "
            "Defaults to the current year-to-date and 22%/15% rates."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "year": {"type": "integer", "minimum": 1990, "maximum": 2100, "description": "Calendar year. Defaults to YTD."},
                "account_id": {"type": "integer", "description": "Restrict to one investment account."},
                "ordinary_marginal_rate": {"type": "number", "minimum": 0, "maximum": 0.5, "description": "Marginal ordinary-income rate for short-term gains. Default 0.22."},
                "ltcg_rate": {"type": "number", "minimum": 0, "maximum": 0.5, "description": "Long-term capital gains rate. Default 0.15."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_merchant_details",
        description=(
            "Deep-dive on a single merchant: year-to-date total, all-time "
            "total, transaction count, 12-month spend trend, and recent "
            "transactions. Matches the name case-insensitively, including "
            "normalized forms ('AMZN Mktp' rolls up under 'Amazon'). The "
            "'how much have I spent at X?' answer."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "merchant_name": {"type": "string", "description": "Merchant display name, e.g. 'Amazon' or 'Whole Foods'."},
            },
            "required": ["merchant_name"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="run_sync",
        description=(
            "Trigger a Plaid sync across all connected items. Same as "
            "clicking 'Sync Now' in the UI. Returns a summary of what was "
            "fetched (accounts updated, transactions added). Call at most "
            "once per conversation — production Plaid syncs are billable and "
            "are not free, so don't hammer this."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    # ── Long-term-hold research layer ────────────────────────────
    Tool(
        name="get_position_research",
        description=(
            "The long-term-hold cockpit: every security the user HOLDS that "
            "the research universe covers, with its overlay — conviction, "
            "upside, tier, next catalyst (flagged if overdue), invalidation "
            "triggers, risk rating, and a stale-research flag — joined onto "
            "the live position (market value, cost basis, unrealized gain/"
            "loss, weight %, accounts, tax buckets). This is the headline "
            "answer to 'for the names I own, is the thesis still intact?'. "
            "Omit domain to use the only/first research domain on disk."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Research domain, e.g. 'critical-minerals'. Omit to auto-pick."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_research_entities",
        description=(
            "The scored research universe (not just held names), ranked by "
            "conviction then upside. Each row carries ticker, name, category, "
            "tier, conviction, upside, risk rating, a one-line thesis, and "
            "whether the user holds it. Filter by tier, minimum conviction, "
            "or held-only. Use when the user asks 'what are the highest-"
            "conviction critical-minerals names?' or 'show me tier-1 only'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Research domain. Omit to auto-pick the only/first one."},
                "tier": {"type": "integer", "minimum": 1, "maximum": 3, "description": "1=producing, 2=near-term, 3=speculative."},
                "min_conviction": {"type": "number", "minimum": 0, "maximum": 100, "description": "Drop names below this conviction score."},
                "held_only": {"type": "boolean", "description": "Only names the user currently holds."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_research_for_ticker",
        description=(
            "Full research dossier for one ticker (across all domains): "
            "thesis summary + detail, every catalyst with status, risks, "
            "invalidation triggers, government support, fundamentals, scoring "
            "factors, sources with confidence, and review cadence. Use when "
            "the user asks 'what's the thesis on MP?' or 'why is USAR "
            "high-conviction?'. Falls back to aliases for class-share/ADR/OTC."
        ),
        inputSchema={
            "type": "object",
            "required": ["ticker"],
            "properties": {
                "ticker": {"type": "string", "description": "Exchange ticker, e.g. 'USAR' or 'MP'."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_research_alerts",
        description=(
            "Derived watch-list for the research universe: large below-cost "
            "positions, overdue catalysts, invalidation-trigger watches on "
            "sizeable holdings, stale research past its review date, and "
            "single-category concentration. Sorted high-severity first. The "
            "'what needs my attention?' answer for a long-term holder. Omit "
            "domain to use the only/first research domain."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Research domain. Omit to auto-pick."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="upsert_research_entity",
        description=(
            "Insert or update one research entity (a full or partial entity "
            "object, matched by id/ticker). The whole file is re-validated "
            "against the JSON Schema before an atomic write, so a malformed "
            "entity is rejected and the file left untouched. A scoring "
            "snapshot is appended to history. Use when the user says 'add "
            "ticker X to the research file' or 're-score Y'. Blocked on "
            "read-only devices and the public demo. Set confidence on "
            "LLM-authored facts to 'medium' until verified."
        ),
        inputSchema={
            "type": "object",
            "required": ["entity"],
            "properties": {
                "domain": {"type": "string", "description": "Research domain to write into. Omit to auto-pick the only/first one."},
                "entity": {"type": "object", "description": "Entity object; must have id or ticker, plus name, security_type, and scores for a brand-new entity."},
                "updated_by": {"type": "string", "description": "Writer label recorded on the entity (default 'claude')."},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="update_research_field",
        description=(
            "Set a single field on one research entity by id — e.g. path "
            "'scores.conviction' value 95, or 'review.next_due' value "
            "'2026-09-12', or 'catalysts[0].status' value 'hit'. Re-validates "
            "and writes atomically; rejects on schema violation. Lighter than "
            "upsert for a one-field tweak. Blocked on read-only devices and "
            "the public demo."
        ),
        inputSchema={
            "type": "object",
            "required": ["id", "path", "value"],
            "properties": {
                "domain": {"type": "string", "description": "Research domain. Omit to auto-pick the only/first one."},
                "id": {"type": "string", "description": "Entity id (stable internal id, usually the ticker)."},
                "path": {"type": "string", "description": "Dotted path, e.g. 'scores.conviction' or 'catalysts[0].status'."},
                "value": {"description": "New value (any JSON type)."},
                "updated_by": {"type": "string", "description": "Writer label (default 'claude')."},
            },
            "additionalProperties": False,
        },
    ),
]


# ── Tool dispatch ────────────────────────────────────────────────

def _format_result(payload: Any) -> str:
    """
    Pretty-print the payload for the assistant. JSON keeps structure
    intact and is what most LLMs handle best.
    """
    return json.dumps(payload, indent=2, default=str)


def _dispatch(name: str, arguments: dict, client: TuskLedgerClient) -> Any:
    """
    Synchronous dispatcher — one branch per tool. Kept linear and
    boring on purpose: each branch is one or two lines and easy to
    audit.
    """
    a = arguments or {}

    if name == "list_accounts":
        return client.list_accounts()
    if name == "list_stale_accounts":
        return client.list_stale_accounts()

    if name == "query_transactions":
        # Trim None / missing keys so we don't send empty params
        params = {k: v for k, v in a.items() if v not in (None, "")}
        params.setdefault("limit", 100)
        return client.list_transactions(**params)
    if name == "search_transactions":
        return client.search_transactions(q=a["q"], limit=a.get("limit", 50))

    if name == "get_spending_summary":
        return client.spending_summary(**{k: v for k, v in a.items() if v not in (None, "")})
    if name == "get_top_merchants":
        params = {k: v for k, v in a.items() if v not in (None, "")}
        params.setdefault("limit", 10)
        return client.top_merchants(**params)
    if name == "get_recurring_subscriptions":
        return client.recurring_subscriptions()

    if name == "get_upcoming_bills":
        return client.upcoming_bills(**{k: v for k, v in a.items() if v not in (None, "")})

    if name == "get_net_worth":
        return client.net_worth_history() if a.get("history") else client.net_worth_latest()

    if name == "get_holdings":
        return client.holdings()
    if name == "get_investments_summary":
        return client.investments_summary()

    if name == "get_retirement_projection":
        # Pass through any params the assistant supplied; the backend
        # validates current_age (required) and assigns sane defaults to
        # the rest. Scrub Nones so the URL stays clean.
        params = {k: v for k, v in a.items() if v not in (None, "")}
        return client.retirement_projection(**params)

    if name == "get_budget":
        if a.get("month") and a.get("year"):
            return client.get_budget(month=a["month"], year=a["year"])
        return client.list_budgets()

    if name == "get_cash_flow_forecast":
        return client.cash_flow_forecast(**{k: v for k, v in a.items() if v not in (None, "")})

    if name == "get_trading_tax_summary":
        return client.trading_tax(**{k: v for k, v in a.items() if v not in (None, "")})

    if name == "get_merchant_details":
        return client.by_merchant(a["merchant_name"])

    if name == "run_sync":
        return client.trigger_sync()

    # ── research ──────────────────────────────────────────────────
    if name == "get_position_research":
        return client.position_research(_resolve_domain(a, client))
    if name == "get_research_entities":
        params = {}
        for k in ("tier", "min_conviction"):
            if a.get(k) not in (None, ""):
                params[k] = a[k]
        if a.get("held_only"):
            params["held_only"] = True
        return client.research_entities(_resolve_domain(a, client), **params)
    if name == "get_research_for_ticker":
        return client.research_for_ticker(a["ticker"])
    if name == "get_research_alerts":
        return client.research_alerts(_resolve_domain(a, client))
    if name == "upsert_research_entity":
        return client.upsert_research_entity(
            _resolve_domain(a, client),
            a.get("entity") or {},
            updated_by=a.get("updated_by", "claude"),
        )
    if name == "update_research_field":
        return client.update_research_field(
            _resolve_domain(a, client),
            a.get("id"),
            a.get("path"),
            a.get("value"),
            updated_by=a.get("updated_by", "claude"),
        )

    raise TuskLedgerError(f"Unknown tool: {name!r}")


def _resolve_domain(a: dict, client: TuskLedgerClient) -> str:
    """Use the caller's `domain`, else the only/first research domain on disk.

    Keeps the research tools usable without the assistant having to know the
    domain key when there's exactly one research file (the common case).
    """
    dom = a.get("domain")
    if dom:
        return dom
    domains = client.research_domains()
    if not domains:
        raise TuskLedgerError(
            "No research domains found. Drop a <domain>.research.json into the "
            "research/ folder (validated against research.schema.json) first."
        )
    return domains[0]["domain"]


# ── Server wiring ────────────────────────────────────────────────

def build_server(client: TuskLedgerClient | None = None) -> Server:
    """
    Construct an MCP Server with the Tusk Ledger tools registered.
    Factored out of main() so tests can build a server instance with a
    mock client.
    """
    server = Server(f"tuskledger-mcp@{__version__}")
    # Default to the production client if none supplied (only tests pass one).
    cli = client or TuskLedgerClient()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        log.info("tool call: %s args=%s", name, list((arguments or {}).keys()))
        try:
            # The HTTP calls are blocking; offload to a thread so we don't
            # stall the event loop. Backend is on localhost so latency is
            # tiny but doing this correctly keeps the door open for
            # async-aware tools later.
            payload = await asyncio.to_thread(_dispatch, name, arguments, cli)
            return [TextContent(type="text", text=_format_result(payload))]
        except TuskLedgerError as e:
            # Surface the error in a way the assistant can show the user.
            err_payload = {
                "error": True,
                "message": str(e),
                "status": e.status,
                "body": e.body,
                "hint": (
                    "If the backend is unreachable, run `./start.sh` from the "
                    "repo root. If the endpoint returned 404 or 500, run "
                    "`./tuskledger doctor --json` for a structured health check."
                ),
            }
            return [TextContent(type="text", text=_format_result(err_payload))]
        except Exception as e:  # pylint: disable=broad-except
            log.exception("tool %s crashed", name)
            err_payload = {
                "error": True,
                "message": f"Unexpected error in {name!r}: {type(e).__name__}: {e}",
                "hint": "Likely a bug in tuskledger-mcp; please file an issue.",
            }
            return [TextContent(type="text", text=_format_result(err_payload))]

    return server


async def serve_stdio() -> None:
    """Run the MCP server over stdio (for Claude Desktop / Cursor / Cowork)."""
    server = build_server()
    log.info(
        "tuskledger-mcp v%s starting on stdio; talking to backend at %s",
        __version__, TuskLedgerClient().base_url,
    )
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
