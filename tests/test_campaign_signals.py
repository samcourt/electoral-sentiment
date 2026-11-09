import csv
import tempfile
import unittest
from pathlib import Path

from campaign_signals import (
    KALSHI_EVENT_TICKER,
    KALSHI_MARKET_FIELDS,
    append_csv_record,
    kalshi_market_snapshot_rows,
    load_csv_or_empty,
)


class CampaignSignalTests(unittest.TestCase):
    def test_kalshi_snapshot_uses_bid_ask_midpoint_and_carries_liquidity(self):
        source = [{
            "ticker": "KXVICTORIANSTATE-26NOV28-LIB",
            "event_ticker": KALSHI_EVENT_TICKER,
            "title": "Victorian state election winner?",
            "yes_sub_title": "Liberals and Nationals",
            "status": "open",
            "yes_bid_dollars": "0.8800",
            "yes_ask_dollars": "0.9200",
            "last_price_dollars": "0.9000",
            "volume_fp": "2500.00",
            "volume_24h_fp": "250.00",
            "open_interest_fp": "1000.00",
            "liquidity_dollars": "125.00",
            "rules_primary": "Resolves to the coalition with most seats.",
        }]
        rows = kalshi_market_snapshot_rows(source)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["implied_chance_pct"], 90.0)
        self.assertAlmostEqual(rows[0]["bid_ask_spread_cents"], 4.0)
        self.assertEqual(rows[0]["volume"], 2500.0)
        self.assertIn("not normalized", rows[0]["source_note"].lower())
        self.assertEqual(set(rows[0]), set(KALSHI_MARKET_FIELDS))

    def test_kalshi_snapshot_falls_back_to_last_trade_without_two_sided_quote(self):
        source = [{
            "ticker": "KXVICTORIANSTATE-26NOV28-ALP",
            "event_ticker": KALSHI_EVENT_TICKER,
            "title": "Victorian state election winner?",
            "yes_sub_title": "Australian Labor Party",
            "last_price_dollars": "0.2300",
        }]
        row = kalshi_market_snapshot_rows(source)[0]
        self.assertAlmostEqual(row["implied_chance_pct"], 23.0)
        self.assertEqual(row["yes_bid_dollars"], None)
        self.assertEqual(row["bid_ask_spread_cents"], None)
        self.assertIn("last trade", row["source_note"].lower())

    def test_append_and_load_csv_keeps_required_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signals.csv"
            record = {field: "" for field in KALSHI_MARKET_FIELDS}
            record.update({
                "snapshot_at": "2026-11-10T12:00:00+11:00",
                "event_ticker": KALSHI_EVENT_TICKER,
                "market_ticker": "TEST",
                "market_outcome": "Test outcome",
            })
            append_csv_record(path, record, KALSHI_MARKET_FIELDS)
            loaded = load_csv_or_empty(path, KALSHI_MARKET_FIELDS)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded.loc[0, "market_ticker"], "TEST")

    def test_append_rejects_schema_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signals.csv"
            path.write_text("wrong_header\n", encoding="utf-8")
            record = {field: "" for field in KALSHI_MARKET_FIELDS}
            with self.assertRaises(ValueError):
                append_csv_record(path, record, KALSHI_MARKET_FIELDS)


if __name__ == "__main__":
    unittest.main()
