"""Transparent exploratory Kew election model.

This module produces polling averages and clearly-labelled scenarios. It is
not a calibrated election forecast and does not infer votes from media tone.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

MODEL_VERSION = "0.1.0"
PRIMARY_COLUMNS = {
    "Labor": "alp_pct",
    "Liberal–National Coalition": "coalition_pct",
    "One Nation": "one_nation_pct",
    "Greens": "greens_pct",
    "Others": "others_pct",
}


def _as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.strip().str.casefold().isin({"true", "1", "yes", "y"})


def _latest_per_pollster(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    work["fieldwork_end_parsed"] = pd.to_datetime(work["fieldwork_end"], errors="coerce")
    work = work.sort_values("fieldwork_end_parsed")
    return work.groupby("pollster", as_index=False, group_keys=False).tail(1)


def calculate_statewide_poll_average(
    poll_path: str | Path,
    as_of: date | None = None,
    half_life_days: float = 14.0,
) -> dict:
    """Recency- and source-weighted average, latest eligible poll per pollster.

    quality_weight is an explicit project judgement stored alongside each poll.
    It is not an official pollster ranking and should be revised after backtesting.
    """
    as_of = as_of or date.today()
    polls = pd.read_csv(poll_path, keep_default_na=False)
    polls["average_eligible"] = _as_bool(polls["average_eligible"])
    eligible = polls[polls["average_eligible"]].copy()
    if eligible.empty:
        raise ValueError("No polls are marked eligible for the default average.")

    eligible["fieldwork_end_parsed"] = pd.to_datetime(
        eligible["fieldwork_end"], errors="coerce"
    )
    eligible = _latest_per_pollster(eligible)
    eligible["age_days"] = (
        pd.Timestamp(as_of) - eligible["fieldwork_end_parsed"]
    ).dt.days.clip(lower=0)
    eligible["quality_weight"] = pd.to_numeric(
        eligible["quality_weight"], errors="coerce"
    ).fillna(0.5)
    eligible["recency_weight"] = 0.5 ** (
        eligible["age_days"] / max(1.0, float(half_life_days))
    )
    eligible["model_weight"] = eligible["quality_weight"] * eligible["recency_weight"]

    averages: dict[str, float | None] = {}
    for label, column in PRIMARY_COLUMNS.items():
        values = pd.to_numeric(eligible[column], errors="coerce")
        valid = values.notna() & eligible["model_weight"].gt(0)
        if valid.any():
            averages[label] = float(
                (values[valid] * eligible.loc[valid, "model_weight"]).sum()
                / eligible.loc[valid, "model_weight"].sum()
            )
        else:
            averages[label] = None

    eligible_tpp = eligible.copy()
    eligible_tpp["coalition_tpp_pct"] = pd.to_numeric(
        eligible_tpp["coalition_tpp_pct"], errors="coerce"
    )
    tpp_valid = eligible_tpp["coalition_tpp_pct"].notna()
    tpp_value = None
    if tpp_valid.any():
        tpp_value = float(
            (
                eligible_tpp.loc[tpp_valid, "coalition_tpp_pct"]
                * eligible_tpp.loc[tpp_valid, "model_weight"]
            ).sum()
            / eligible_tpp.loc[tpp_valid, "model_weight"].sum()
        )

    weight_total = float(eligible["model_weight"].sum())
    eligible["normalised_weight_pct"] = (
        eligible["model_weight"] / weight_total * 100 if weight_total else 0
    )
    return {
        "as_of": as_of.isoformat(),
        "primary_average": averages,
        "coalition_tpp_average": tpp_value,
        "polls_used": eligible.sort_values("fieldwork_end_parsed", ascending=False),
        "half_life_days": float(half_life_days),
        "method": (
            "Latest eligible poll per pollster; pollster quality weight × "
            f"14-day exponential half-life (configured: {half_life_days:g} days)."
        ),
    }


def _numeric_share(history: pd.DataFrame, candidate_name: str | None = None,
                   party_contains: str | None = None) -> float | None:
    if history.empty:
        return None
    rows = history[history["result_measure"] == "primary"].copy()
    if candidate_name:
        rows = rows[rows["candidate_name"].astype(str).str.casefold() == candidate_name.casefold()]
    elif party_contains:
        rows = rows[rows["party"].astype(str).str.contains(party_contains, case=False, na=False)]
    if rows.empty:
        return None
    return float(pd.to_numeric(rows["share_pct"], errors="coerce").iloc[0])


def _seat_poll_anchors(poll_path: str | Path) -> dict:
    polls = pd.read_csv(poll_path, keep_default_na=False)
    values: dict[str, float] = {}
    for _, row in polls.iterrows():
        option = str(row.get("option_label", "")).casefold()
        value = pd.to_numeric(pd.Series([row.get("reported_pct", "")]), errors="coerce").iloc[0]
        if pd.isna(value):
            continue
        if "jess wilson" in option:
            values["Jess Wilson"] = float(value)
        elif "sophie torney" in option:
            values["Sophie Torney"] = float(value)
        elif "labor" in option:
            values["Labor party (candidate not identified)"] = float(value)
        elif "one nation" in option:
            values["One Nation party (candidate not selected)"] = float(value)
    return values


def build_kew_candidate_scenario(
    candidates_path: str | Path,
    history_path: str | Path,
    seat_poll_path: str | Path,
    state_average: dict,
    march_poll_path: str | Path,
    pass_through: float = 1.0,
) -> pd.DataFrame:
    """Map statewide poll movement onto a dated Kew poll and historical local anchors.

    This intentionally leaves candidates with no defensible baseline unestimated and
    allocates the remaining vote to an explicit unallocated bucket.
    """
    candidates = pd.read_csv(candidates_path, keep_default_na=False)
    history = pd.read_csv(history_path, keep_default_na=False)
    march = pd.read_csv(march_poll_path, keep_default_na=False)
    anchors = _seat_poll_anchors(seat_poll_path)

    march = march[march["poll_id"].astype(str) == "RESOLVE-MAR-2026"]
    if march.empty:
        raise ValueError("March 2026 Resolve reference poll is missing.")
    march_row = march.iloc[0]
    march_values = {
        "Labor": float(march_row["alp_pct"]),
        "Liberal–National Coalition": float(march_row["coalition_pct"]),
        "One Nation": float(march_row["one_nation_pct"]),
        "Greens": float(march_row["greens_pct"]),
    }
    current_values = state_average["primary_average"]
    party_delta = {
        party: float(current_values[party] - base)
        for party, base in march_values.items()
        if current_values.get(party) is not None
    }

    history_rows = history[history["result_measure"] == "primary"].copy()
    historical_candidates = {
        str(row["candidate_name"]): float(row["share_pct"])
        for _, row in history_rows.iterrows()
    }
    national_socialist_proxy = 1.35  # 2022 statewide Victorian Socialists first preference
    rows = []

    for _, candidate in candidates.sort_values("ballot_order").iterrows():
        name = str(candidate["candidate_name"])
        party = str(candidate["party"])
        base = None
        basis = ""
        delta_key = None

        if name in {"Jess Wilson", "Sophie Torney"} and name in anchors:
            base = anchors[name]
            basis = (
                "March 2026 Kew uComms candidate-specific poll anchor "
                "(campaign-commissioned; incomplete reported options)"
            )
            if name == "Jess Wilson":
                delta_key = "Liberal–National Coalition"
        elif name == "David Sun" and "Labor party (candidate not identified)" in anchors:
            base = anchors["Labor party (candidate not identified)"]
            basis = (
                "March 2026 Kew Labor party-intention poll anchor; candidate not identified "
                "in the poll report, so this is not a personal candidate measure"
            )
            delta_key = "Labor"
        elif name == "David Laird" and "One Nation party (candidate not selected)" in anchors:
            base = anchors["One Nation party (candidate not selected)"]
            basis = (
                "March 2026 Kew One Nation party-intention poll anchor; candidate had not "
                "been selected at the time, so this is not a personal candidate measure"
            )
            delta_key = "One Nation"
        elif party == "The Greens":
            base = historical_candidates.get("Jackie Carter")
            basis = "2022 Kew Greens candidate result, adjusted by statewide Greens polling movement since March"
            delta_key = "Greens"
        elif party == "Family First Victoria":
            base = historical_candidates.get("Ann Seeley")
            basis = "2022 Kew Family First candidate result; no current seat-level poll"
        elif party == "Animal Justice Party":
            base = historical_candidates.get("Ruby Schofield")
            basis = "2022 Kew Animal Justice result used as party proxy; candidate differs"
        elif party == "Victorian Socialists":
            base = national_socialist_proxy
            basis = "2022 statewide Victorian Socialists vote used as a weak proxy; no Kew result"
        elif name == "Finlay Davis":
            base = historical_candidates.get("Finlay Davis")
            basis = "2022 Kew result for the same independent candidate"
        else:
            basis = "No direct Kew poll or defensible historical local baseline"

        estimate = None
        delta = 0.0
        if base is not None:
            if delta_key and delta_key in party_delta:
                delta = party_delta[delta_key] * float(pass_through)
            estimate = max(0.0, min(100.0, float(base) + delta))

        rows.append({
            "candidate_name": name,
            "party": party,
            "ballot_order": int(candidate["ballot_order"]),
            "primary_estimate_pct": estimate,
            "baseline_pct": base,
            "statewide_adjustment_pct": delta,
            "estimate_basis": basis,
            "estimate_status": "Exploratory scenario" if estimate is not None else "Not estimable from current inputs",
            "confidence_label": "Very low — unvalidated" if estimate is not None else "No estimate",
        })

    estimated_total = sum(
        row["primary_estimate_pct"] for row in rows
        if row["primary_estimate_pct"] is not None
    )
    residual = max(0.0, 100.0 - estimated_total)
    rows.append({
        "candidate_name": "Unallocated / unmodelled vote",
        "party": "Residual",
        "ballot_order": 999,
        "primary_estimate_pct": residual,
        "baseline_pct": None,
        "statewide_adjustment_pct": None,
        "estimate_basis": (
            "Residual required to bring the partial candidate scenario to 100%. "
            "Includes Man Liang and any unreported or unmodelled vote; it is not a candidate estimate."
        ),
        "estimate_status": "Unallocated residual",
        "confidence_label": "Not a candidate forecast",
    })

    return pd.DataFrame(rows)


def calculate_kew_labor_coalition_scenario(
    state_average: dict,
    uniform_swing_multiplier: float = 1.0,
) -> dict:
    """Conditional Wilson-versus-Labor share using a uniform-swing reference."""
    current_tpp = state_average.get("coalition_tpp_average")
    if current_tpp is None:
        return {"available": False, "reason": "No eligible statewide two-party poll results."}

    historic_kew_coalition = 53.98
    historic_state_coalition = 45.0
    change = float(current_tpp) - historic_state_coalition
    projected = max(
        0.0,
        min(100.0, historic_kew_coalition + change * float(uniform_swing_multiplier)),
    )
    return {
        "available": True,
        "coalition_candidate": "Jess Wilson",
        "labor_candidate": "David Sun",
        "coalition_share_pct": projected,
        "labor_share_pct": 100.0 - projected,
        "current_statewide_coalition_tpp_pct": float(current_tpp),
        "historic_kew_coalition_share_pct": historic_kew_coalition,
        "historic_statewide_coalition_tpp_pct": historic_state_coalition,
        "statewide_share_change_pp": change,
        "uniform_swing_multiplier": float(uniform_swing_multiplier),
        "sensitivity_low_pct": historic_kew_coalition + change * 0.5,
        "sensitivity_high_pct": historic_kew_coalition + change * 1.5,
        "interpretation": (
            "Conditional Wilson-versus-Sun scenario. Applies a selectable fraction of the "
            "statewide Coalition two-party share change to Kew's 2022 final Liberal-versus-Labor "
            "distribution. It assumes the same final pair and a uniform swing; it is not a forecast "
            "of which candidates finish first and second."
        ),
    }


def make_snapshot_rows(
    snapshot_date: str,
    candidate_scenario: pd.DataFrame,
    tpp_scenario: dict,
) -> pd.DataFrame:
    records = []
    for _, row in candidate_scenario.iterrows():
        estimate = row["primary_estimate_pct"]
        records.append({
            "snapshot_date": snapshot_date,
            "model_version": MODEL_VERSION,
            "metric_type": "candidate_primary_scenario",
            "candidate_name": row["candidate_name"],
            "estimate_pct": estimate,
            "low_sensitivity_pct": (
                row.get("sensitivity_low_pct", "")
                if pd.notna(row.get("sensitivity_low_pct", "")) else ""
            ),
            "high_sensitivity_pct": (
                row.get("sensitivity_high_pct", "")
                if pd.notna(row.get("sensitivity_high_pct", "")) else ""
            ),
            "assumption": row["estimate_basis"],
        })
    if tpp_scenario.get("available"):
        records.append({
            "snapshot_date": snapshot_date,
            "model_version": MODEL_VERSION,
            "metric_type": "conditional_wilson_vs_sun",
            "candidate_name": "Jess Wilson",
            "estimate_pct": tpp_scenario["coalition_share_pct"],
            "low_sensitivity_pct": tpp_scenario["sensitivity_low_pct"],
            "high_sensitivity_pct": tpp_scenario["sensitivity_high_pct"],
            "assumption": tpp_scenario["interpretation"],
        })
    return pd.DataFrame(records)
