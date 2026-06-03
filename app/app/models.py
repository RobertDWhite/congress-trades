import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(256))
    name_norm: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    bioguide: Mapped[str | None] = mapped_column(String(16), index=True)  # join key to congress.gov
    chamber: Mapped[str | None] = mapped_column(String(16))
    party: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str | None] = mapped_column(String(8))
    district: Mapped[str | None] = mapped_column(String(8))
    # Estimated net worth from the latest annual Financial Disclosure (asset-range
    # midpoints minus liabilities). Range because disclosures are reported as $ brackets.
    net_worth_min: Mapped[int | None] = mapped_column(Numeric)
    net_worth_max: Mapped[int | None] = mapped_column(Numeric)
    net_worth_year: Mapped[int | None] = mapped_column(Integer)
    # committee memberships (from unitedstates/congress-legislators) + derived oversight sectors
    committees: Mapped[list | None] = mapped_column(JSON)
    committee_sectors: Mapped[list | None] = mapped_column(JSON)


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # house | senate
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    chamber: Mapped[str | None] = mapped_column(String(16))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    filing_type: Mapped[str | None] = mapped_column(String(8))
    filing_date: Mapped[dt.date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(Text)
    # pending | parsed | ocr | paper | error
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")
    raw_text: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("source", "doc_id", name="uq_filing_source_doc"),)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"))
    source: Mapped[str] = mapped_column(String(32), index=True)  # house_primary | senate_primary | lambda
    source_priority: Mapped[int] = mapped_column(Integer, default=1)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    chamber: Mapped[str | None] = mapped_column(String(16), index=True)
    transaction_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    disclosure_date: Mapped[dt.date | None] = mapped_column(Date)
    owner: Mapped[str | None] = mapped_column(String(32))
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    asset_name: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[str | None] = mapped_column(String(64))
    transaction_type: Mapped[str | None] = mapped_column(String(16), index=True)
    amount_min: Mapped[int | None] = mapped_column(Numeric)
    amount_max: Mapped[int | None] = mapped_column(Numeric)
    amount_range_raw: Mapped[str | None] = mapped_column(String(64))
    cap_gains_over_200: Mapped[bool | None] = mapped_column(Boolean)
    comment: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # follower performance: entry = close on/after disclosure_date (the date you could act),
    # return to latest close, and the same-window SPY benchmark. Precomputed nightly.
    entry_price: Mapped[float | None] = mapped_column(Numeric)
    return_pct: Mapped[float | None] = mapped_column(Numeric)
    bench_return_pct: Mapped[float | None] = mapped_column(Numeric)
    option_type: Mapped[str | None] = mapped_column(String(8))  # call | put
    option_strike: Mapped[float | None] = mapped_column(Numeric)
    option_expiration: Mapped[dt.date | None] = mapped_column(Date)

    __table_args__ = (
        # dominant access patterns: member detail and ticker detail, newest-first
        Index("ix_trades_member_txdate", "member_id", "transaction_date"),
        Index("ix_trades_ticker_txdate", "ticker", "transaction_date"),
        Index("ix_trades_disclosure_date", "disclosure_date"),
    )


class IngestState(Base):
    """Per-source incremental-fetch state (conditional GET / change detection)."""

    __tablename__ = "ingest_state"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. house:2026
    etag: Mapped[str | None] = mapped_column(String(256))
    last_modified: Mapped[str | None] = mapped_column(String(128))
    content_length: Mapped[int | None] = mapped_column(Integer)
    last_success: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_run: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rows_upserted: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)


class TradeSignal(Base):
    """A scored 'interesting' attribute of a trade (cluster buy, large, options, lag, …)."""

    __tablename__ = "trade_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    signal_type: Mapped[str] = mapped_column(String(32), index=True)
    score: Mapped[int] = mapped_column(Integer, default=1)
    detail: Mapped[dict | None] = mapped_column(JSON)
    alerted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("trade_id", "signal_type", name="uq_signal_trade_type"),)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # member | ticker
    value: Mapped[str] = mapped_column(String(64))  # member_id (str) or ticker
    min_score: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (UniqueConstraint("kind", "value", name="uq_watch_kind_value"),)


class TickerPrice(Base):
    """Latest daily close per ticker (Stooq), for return-since-disclosure / share counts."""

    __tablename__ = "ticker_prices"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    close: Mapped[float | None] = mapped_column(Numeric)
    as_of: Mapped[dt.date | None] = mapped_column(Date)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TickerBar(Base):
    """Historical daily closes (Stooq) — enables entry-price/return-since-disclosure, leaderboards,
    and benchmarking vs SPY. Benchmarks (SPY/QQQ) are stored as normal tickers."""

    __tablename__ = "ticker_bars"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    bar_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Numeric)


class TickerMeta(Base):
    """Sector/industry/company metadata from SEC (company_tickers + submissions) + sentiment."""

    __tablename__ = "ticker_meta"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    cik: Mapped[str | None] = mapped_column(String(16), index=True)
    company: Mapped[str | None] = mapped_column(String(256))
    sic: Mapped[str | None] = mapped_column(String(8))
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    sentiment: Mapped[float | None] = mapped_column(Numeric)  # StockTwits bull-bear ratio -1..1
    sentiment_n: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TickerAlias(Base):
    """Best-effort aliases for mapping disclosed asset names to canonical tickers."""

    __tablename__ = "ticker_aliases"

    alias: Mapped[str] = mapped_column(String(256), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TickerQuote(Base):
    """Live-ish last price (Yahoo 1m) for live return-since-disclosure."""

    __tablename__ = "ticker_quotes"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    last: Mapped[float | None] = mapped_column(Numeric)
    market_state: Mapped[str | None] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(32))
    as_of: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class GovEvent(Base):
    """SEC EDGAR near-real-time filings (Form 4 insider, 8-K) keyed to a ticker via CIK."""

    __tablename__ = "gov_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # edgar
    form: Mapped[str | None] = mapped_column(String(16), index=True)  # 4 | 8-K
    cik: Mapped[str | None] = mapped_column(String(16), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    filed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    accession: Mapped[str] = mapped_column(String(32), unique=True)


class LegislativeEvent(Base):
    """Congress.gov context near a trade: bills, votes, amendments, and committee activity."""

    __tablename__ = "legislative_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="congress.gov")
    event_type: Mapped[str] = mapped_column(String(32), index=True)  # bill | vote | committee
    congress: Mapped[int | None] = mapped_column(Integer)
    chamber: Mapped[str | None] = mapped_column(String(16), index=True)
    bioguide: Mapped[str | None] = mapped_column(String(16), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    committee: Mapped[str | None] = mapped_column(String(256))
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True)
    payload: Mapped[dict | None] = mapped_column(JSON)


class TradeReconciliation(Base):
    """Cross-source data-quality checks between primary parsers and comparison feeds."""

    __tablename__ = "trade_reconciliation"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # missing_primary | missing_comparison | mismatch
    primary_trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), index=True)
    comparison_source: Mapped[str | None] = mapped_column(String(32), index=True)
    comparison_trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), index=True)
    severity: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float | None] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | resolved | ignored
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    __table_args__ = (
        UniqueConstraint("kind", "primary_trade_id", "comparison_source", "comparison_trade_id", name="uq_recon_issue"),
    )


class StrategyRun(Base):
    """Cached backtest of a 'follow-strategy' portfolio (equity curve + metrics vs benchmarks)."""

    __tablename__ = "strategy_runs"

    strategy_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(128))
    params: Mapped[dict | None] = mapped_column(JSON)
    equity_curve: Mapped[list | None] = mapped_column(JSON)  # [[date, value, spy, nanc?], ...]
    holdings: Mapped[list | None] = mapped_column(JSON)       # current smart-money basket
    total_return: Mapped[float | None] = mapped_column(Numeric)
    cagr: Mapped[float | None] = mapped_column(Numeric)
    max_drawdown: Mapped[float | None] = mapped_column(Numeric)
    excess_vs_spy: Mapped[float | None] = mapped_column(Numeric)
    n_positions: Mapped[int | None] = mapped_column(Integer)
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Holding(Base):
    """User paper-portfolio holding (single user behind SSO)."""

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    shares: Mapped[float | None] = mapped_column(Numeric)
    cost_basis: Mapped[float | None] = mapped_column(Numeric)
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("ticker", name="uq_holding_ticker"),)


class TickerFundamentals(Base):
    """Company financials from SEC EDGAR companyfacts (free/public, keyed by CIK).

    Latest annual (10-K) revenue/net income/assets/EPS plus the most recent quarterly
    (10-Q) figures, used for dossier fundamentals context and the conflict score's
    'company fundamentals' component. Refreshed periodically; degrades gracefully when absent."""

    __tablename__ = "ticker_fundamentals"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    cik: Mapped[str | None] = mapped_column(String(16), index=True)
    company: Mapped[str | None] = mapped_column(String(256))
    # latest annual figures
    fy: Mapped[int | None] = mapped_column(Integer)
    fy_end: Mapped[dt.date | None] = mapped_column(Date)
    revenue: Mapped[float | None] = mapped_column(Numeric)
    net_income: Mapped[float | None] = mapped_column(Numeric)
    assets: Mapped[float | None] = mapped_column(Numeric)
    eps_diluted: Mapped[float | None] = mapped_column(Numeric)
    shares_out: Mapped[float | None] = mapped_column(Numeric)
    revenue_prior: Mapped[float | None] = mapped_column(Numeric)  # prior FY revenue, for YoY
    revenue_yoy: Mapped[float | None] = mapped_column(Numeric)    # fractional growth, e.g. 0.12
    # most recent quarterly figures
    q_end: Mapped[dt.date | None] = mapped_column(Date)
    q_revenue: Mapped[float | None] = mapped_column(Numeric)
    q_net_income: Mapped[float | None] = mapped_column(Numeric)
    latest_form: Mapped[str | None] = mapped_column(String(8))     # 10-K | 10-Q (headline source)
    source_url: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AiSummary(Base):
    __tablename__ = "ai_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)  # global | member
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    window_days: Mapped[int] = mapped_column(Integer)
    summary_md: Mapped[str | None] = mapped_column(Text)
    observations: Mapped[list | None] = mapped_column(JSON)
    watchlist: Mapped[list | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(64))
    data_hash: Mapped[str | None] = mapped_column(String(64))
    trade_count: Mapped[int | None] = mapped_column(Integer)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class GovContract(Base):
    """Federal awards (USASpending.gov, free/public) joined to a traded ticker by recipient name."""

    __tablename__ = "gov_contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    award_id: Mapped[str] = mapped_column(String(64), unique=True)  # generated_internal_id / PIID
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    recipient_name: Mapped[str | None] = mapped_column(String(256))
    awarding_agency: Mapped[str | None] = mapped_column(String(256))
    award_type: Mapped[str | None] = mapped_column(String(32))  # contract | grant | loan
    award_amount: Mapped[float | None] = mapped_column(Numeric)
    action_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class LobbyingRecord(Base):
    """Federal lobbying disclosures (Senate LDA API, free/public) joined to a ticker by client name."""

    __tablename__ = "lobbying_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_uuid: Mapped[str] = mapped_column(String(64), unique=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    client_name: Mapped[str | None] = mapped_column(String(256))
    registrant_name: Mapped[str | None] = mapped_column(String(256))
    amount: Mapped[float | None] = mapped_column(Numeric)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    period: Mapped[str | None] = mapped_column(String(32))  # filing period
    issues: Mapped[list | None] = mapped_column(JSON)        # general issue area codes/descriptions
    url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class EtfHolding(Base):
    """Holdings of the congress-tracking ETFs (NANC/KRUZ) for an overlap/benchmark view."""

    __tablename__ = "etf_holdings"

    etf: Mapped[str] = mapped_column(String(16), primary_key=True)     # NANC | KRUZ
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    company: Mapped[str | None] = mapped_column(String(256))
    weight: Mapped[float | None] = mapped_column(Numeric)             # fractional weight 0..1
    shares: Mapped[float | None] = mapped_column(Numeric)
    as_of: Mapped[dt.date | None] = mapped_column(Date)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class MacroSeries(Base):
    """Latest FRED macro series snapshot (rates, CPI, unemployment, treasury yields) for context."""

    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g. FEDFUNDS, CPIAUCSL
    title: Mapped[str | None] = mapped_column(String(256))
    value: Mapped[float | None] = mapped_column(Numeric)
    prev_value: Mapped[float | None] = mapped_column(Numeric)
    units: Mapped[str | None] = mapped_column(String(64))
    as_of: Mapped[dt.date | None] = mapped_column(Date)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AlertRule(Base):
    """User-configurable alert rule. Evaluated against new trades; delivered to its channels."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    # member | ticker | large | cluster | conflict | late | options | event_proximity
    rule_type: Mapped[str] = mapped_column(String(32), index=True)
    params: Mapped[dict | None] = mapped_column(JSON)     # {member_id, ticker, sector, min_amount, min_conviction, ...}
    channels: Mapped[list | None] = mapped_column(JSON)   # [{"type":"ntfy|email|webhook","target":"..."}]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    account_token: Mapped[str | None] = mapped_column(String(64), index=True)  # null = global/legacy
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_fired_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AlertDelivery(Base):
    """De-dup + audit log of a rule firing for a given trade."""

    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(16))  # sent | failed | skipped
    fired_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("rule_id", "trade_id", name="uq_alert_rule_trade"),)


class UserAccount(Base):
    """Lightweight, token-based account: cloud-synced prefs (watchlist, alert channels, filters).
    No password — the opaque token IS the credential, stored client-side. Single-table, optional."""

    __tablename__ = "user_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    handle: Mapped[str | None] = mapped_column(String(64))
    prefs: Mapped[dict | None] = mapped_column(JSON)  # {watchlist:[...], saved_filters:[...], digest_email:...}
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
