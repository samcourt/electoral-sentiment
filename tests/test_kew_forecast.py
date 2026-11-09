import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from kew_forecast import (
    build_kew_candidate_scenario,
    calculate_kew_labor_coalition_scenario,
    calculate_statewide_poll_average,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class KewForecastTests(unittest.TestCase):
    def test_statewide_poll_average_is_complete(self):
        average = calculate_statewide_poll_average(
            DATA / "vic_state_polls_2026.csv",
            as_of=date(2026, 11, 10),
        )
        shares = list(average["primary_average"].values())
        self.assertTrue(all(value is not None for value in shares))
        self.assertAlmostEqual(sum(shares), 100.0, places=6)
        self.assertGreater(average["primary_average"]["Liberal–National Coalition"], 29)
        self.assertGreater(average["primary_average"]["One Nation"], 19)
        self.assertIsNotNone(average["coalition_tpp_average"])

    def test_candidate_scenario_keeps_unmeasured_candidate_unestimated(self):
        average = calculate_statewide_poll_average(
            DATA / "vic_state_polls_2026.csv",
            as_of=date(2026, 11, 10),
        )
        scenario = build_kew_candidate_scenario(
            DATA / "kew_2026_candidates.csv",
            DATA / "kew_2022_results.csv",
            DATA / "kew_polls.csv",
            average,
            DATA / "vic_state_polls_2026.csv",
            pass_through=1.0,
        )
        man_liang = scenario[scenario["candidate_name"] == "Man Liang"].iloc[0]
        self.assertTrue(pd.isna(man_liang["primary_estimate_pct"]))
        residual = scenario[scenario["candidate_name"] == "Unallocated / unmodelled vote"].iloc[0]
        self.assertGreater(residual["primary_estimate_pct"], 0)
        estimates = scenario["primary_estimate_pct"].dropna()
        self.assertAlmostEqual(float(estimates.sum()), 100.0, places=5)

    def test_uniform_swing_scenario_is_conditional_and_bounded(self):
        average = calculate_statewide_poll_average(
            DATA / "vic_state_polls_2026.csv",
            as_of=date(2026, 11, 10),
        )
        scenario = calculate_kew_labor_coalition_scenario(average, 1.0)
        self.assertTrue(scenario["available"])
        self.assertEqual(scenario["coalition_candidate"], "Jess Wilson")
        self.assertEqual(scenario["labor_candidate"], "David Sun")
        self.assertGreater(scenario["coalition_share_pct"], 53.98)
        self.assertAlmostEqual(
            scenario["coalition_share_pct"] + scenario["labor_share_pct"],
            100.0,
            places=6,
        )
        self.assertIn("not a forecast", scenario["interpretation"].lower())


if __name__ == "__main__":
    unittest.main()
