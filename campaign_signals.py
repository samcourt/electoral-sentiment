"""Campaign effort, public donation disclosure and prediction-market signals.

These records describe campaign capacity and observable activity, not voter
preferences. Kalshi data is retrieved from its public unauthenticated market-data API.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import requests

KALSHI_API = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_EVENT_TICKER = "KXVICTORIANSTATE-26NOV28"
KALSHI_EVENT_URL = (
    "https://kalshi.com/markets/kxvictorianstate/victorian-state-election/"
    "kxvictorianstate-26nov28"
)
VEC_DISCLOSURES_URL = "https://disclosures.vec.vic.gov.au/public-donations/"
VEC_DONATIONS_GUIDANCE_URL = (
    "https://www.vec.vic.gov.au/candidates-and-parties/political-donations"
)

DONATION_FIELDS = [
    "record_id", "donation_date", "disclosure_date", "recipient_name",
    "recipient_type", "donor_category", "amount_aud", "geographic_scope",
    "source_url", "source_note", "recorded_at", "electorate",
]
ACTIVITY_FIELDS = [
    "activity_id", "activity_date", "recorded_at", "candidate_name", "party",
    "activity_type", "activity_status", "location_suburb", "location_detail",
    "volunteers_reported", "doors_contacted_reported", "source_type",
    "source_url", "evidence_note", "electorate",
]
MARKET_FIELDS = [
    "snapshot_at", "event_ticker", "market_ticker", "market_title",
    "market_outcome", "market_status", "yes_bid_dollars", "yes_ask_dollars",
    "yes_mid_dollars", "last_price_dollars", "implied_chance_pct",
    "bid_ask_spread_cents", "volume", "volume_24h", "open_interest",
    "liquidity_dollars", "market_url", "rules_primary", "source_note",
]

KALSHI_MARKET_FIELDS = MARKET_FIELDS
ANALYST_FIELDS = [
    "record_id", "published_date", "analyst", "title", "coverage",
    "analysis_type", "key_points", "interpretation_limit", "source_url",
    "review_status", "recorded_at",
]


def sydney_now() -> str:
    return datetime.now(ZoneInfo("Australia/Sydney")).isoformat(timespec="seconds")


def append_csv_record(path: str | Path, record: dict, fieldnames: Iterable[str]) -> None:
    """Append a single validated record while preserving a stable CSV schema."""
    path = Path(path)
    fields = list(fieldnames)
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError("Record is missing required fields: " + ", ".join(missing))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([{field: record.get(field, "") for field in fields}])
    if path.exists() and path.stat().st_size:
        existing = pd.read_csv(path, keep_default_na=False)
        if list(existing.columns) != fields:
            raise ValueError(
                f"CSV schema mismatch in {path}: expected {fields}, "
                f"found {list(existing.columns)}"
            )
        combined = pd.concat([existing, frame], ignore_index=True)
    else:
        combined = frame
    combined.to_csv(path, index=False)


def _float_or_none(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _clean_probability_fields(market: dict) -> dict:
    bid = _float_or_none(market.get("yes_bid_dollars"))
    ask = _float_or_none(market.get("yes_ask_dollars"))
    last = _float_or_none(market.get("last_price_dollars"))

    if bid is not None and ask is not None and 0 <= bid <= ask <= 1:
        midpoint = (bid + ask) / 2
        spread = (ask - bid) * 100
        price_basis = "midpoint"
    elif last is not None and 0 <= last <= 1:
        midpoint = last
        spread = None
        price_basis = "last trade (no usable two-sided quote)"
    else:
        midpoint = None
        spread = None
        price_basis = "no usable price"

    return {
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "yes_mid_dollars": midpoint,
        "last_price_dollars": last,
        "implied_chance_pct": midpoint * 100 if midpoint is not None else None,
        "bid_ask_spread_cents": spread,
        "price_basis": price_basis,
    }


def fetch_kalshi_event_markets(
    event_ticker: str = KALSHI_EVENT_TICKER,
    timeout: tuple[int, int] = (8, 20),
) -> list[dict]:
    """Return public market data for a Kalshi event. No API key is required."""
    url = f"{KALSHI_API}/markets"
    response = requests.get(
        url,
        params={"event_ticker": event_ticker, "limit": 100},
        headers={"User-Agent": "electoral-sentiment-tracker/0.6"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        raise ValueError("Kalshi API returned an unexpected markets payload.")
    matches = [
        market for market in markets
        if str(market.get("event_ticker", "")) == event_ticker
    ]
    if not matches:
        raise ValueError(
            f"Kalshi returned no markets for event ticker {event_ticker}. "
            "Check whether the contract is still open or the ticker has changed."
        )
    return matches


def kalshi_market_snapshot_rows(
    markets: list[dict],
    event_ticker: str = KALSHI_EVENT_TICKER,
) -> list[dict]:
    """Convert API market responses into stable, chart-ready snapshot rows."""
    snapshot_at = sydney_now()
    rows = []
    for market in markets:
        prices = _clean_probability_fields(market)
        ticker = str(market.get("ticker", ""))
        title = str(market.get("title", ""))
        subtitle = str(market.get("yes_sub_title", "") or market.get("subtitle", ""))
        outcome = subtitle or title
        market_url = (
            "https://kalshi.com/markets/kxvictorianstate/"
            "victorian-state-election/" + event_ticker.casefold()
        )
        rows.append({
            "snapshot_at": snapshot_at,
            "event_ticker": event_ticker,
            "market_ticker": ticker,
            "market_title": title,
            "market_outcome": outcome,
            "market_status": str(market.get("status", "")),
            "yes_bid_dollars": prices["yes_bid_dollars"],
            "yes_ask_dollars": prices["yes_ask_dollars"],
            "yes_mid_dollars": prices["yes_mid_dollars"],
            "last_price_dollars": prices["last_price_dollars"],
            "implied_chance_pct": prices["implied_chance_pct"],
            "bid_ask_spread_cents": prices["bid_ask_spread_cents"],
            "volume": _float_or_none(market.get("volume_fp")),
            "volume_24h": _float_or_none(market.get("volume_24h_fp")),
            "open_interest": _float_or_none(market.get("open_interest_fp")),
            "liquidity_dollars": _float_or_none(market.get("liquidity_dollars")),
            "market_url": market_url,
            "rules_primary": str(market.get("rules_primary", "")),
            "source_note": (
                "Public Kalshi market-data API. Implied chance uses YES bid/ask midpoint "
                "when both sides are available; otherwise last traded price. Prices are "
                "not normalized across mutually exclusive contracts and may not sum to 100%. "
                f"Price basis: {prices['price_basis']}."
            ),
        })
    return rows


def load_csv_or_empty(path: str | Path, fields: Iterable[str]) -> pd.DataFrame:
    path = Path(path)
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame(columns=list(fields))
    frame = pd.read_csv(path, keep_default_na=False)
    return frame
