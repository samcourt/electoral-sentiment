import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from news_monitor import collect_news
from campaign_signals import (
    ACTIVITY_FIELDS,
    ANALYST_FIELDS,
    DONATION_FIELDS,
    KALSHI_EVENT_TICKER,
    KALSHI_EVENT_URL,
    KALSHI_MARKET_FIELDS,
    VEC_DISCLOSURES_URL,
    append_csv_record,
    fetch_kalshi_event_markets,
    kalshi_market_snapshot_rows,
    load_csv_or_empty,
    sydney_now,
)
from kew_forecast import (
    MODEL_VERSION,
    build_kew_candidate_scenario,
    calculate_kew_labor_coalition_scenario,
    calculate_statewide_poll_average,
    make_snapshot_rows,
)

LOCAL_TODAY = datetime.now(ZoneInfo("Australia/Sydney")).date()

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DISTRICTS_PATH = DATA_DIR / "vic_districts_2026.csv"
OBSERVATIONS_PATH = DATA_DIR / "kew_seed_observations.csv"
NEWS_PATH = DATA_DIR / "news_articles.csv"
RESULTS_PATH = DATA_DIR / "vic_2022_district_results.csv"
KEW_CANDIDATES_PATH = DATA_DIR / "kew_2026_candidates.csv"
KEW_RESULTS_PATH = DATA_DIR / "kew_2022_results.csv"
KEW_POLLS_PATH = DATA_DIR / "kew_polls.csv"
VIC_STATE_POLLS_PATH = DATA_DIR / "vic_state_polls_2026.csv"
KEW_EXTERNAL_FORECAST_PATH = DATA_DIR / "kew_external_forecast_benchmarks.csv"
KEW_EXTERNAL_2CP_PATH = DATA_DIR / "kew_external_2cp_benchmarks.csv"
VIC_POLL_AVERAGE_BENCHMARK_PATH = DATA_DIR / "vic_poll_average_benchmarks.csv"
KEW_FORECAST_SNAPSHOTS_PATH = DATA_DIR / "kew_forecast_snapshots.csv"
KEW_DONATIONS_PATH = DATA_DIR / "kew_campaign_donations.csv"
KEW_ACTIVITY_PATH = DATA_DIR / "kew_campaign_activity.csv"
KALSHI_SNAPSHOTS_PATH = DATA_DIR / "kalshi_market_snapshots.csv"
ANTONY_GREEN_NOTES_PATH = DATA_DIR / "antony_green_notes.csv"

st.set_page_config(
    page_title="Electoral Sentiment Tracker",
    page_icon="📊",
    layout="wide",
)

@st.cache_data
def load_districts():
    """Load the VEC district register; keep the Kew pilot usable if it is absent."""
    if DISTRICTS_PATH.exists():
        districts = pd.read_csv(DISTRICTS_PATH)
        if "district" in districts.columns:
            return districts, True
    return pd.DataFrame([{
        "district": "Kew",
        "vec_url": "https://vec.vic.gov.au/electoral-boundaries/state-districts"
    }]), False

@st.cache_data
def load_observations():
    """Load source-linked observations without turning labels into numeric scores."""
    if not OBSERVATIONS_PATH.exists():
        return pd.DataFrame()
    observations = pd.read_csv(OBSERVATIONS_PATH, keep_default_na=False)
    required = {
        "observation_id", "observation_date", "electorate", "geographic_scope",
        "source_name", "source_type", "issue", "observation", "sentiment_label",
        "evidence_class", "confidence", "representativeness", "source_url"
    }
    missing = required.difference(observations.columns)
    if missing:
        st.error("The observations CSV is missing required columns: " + ", ".join(sorted(missing)))
        return pd.DataFrame()

    # Date ranges such as 2025-03/2025-04 are anchored to their start month.
    def parse_observation_date(value):
        value = str(value).split("/")[0].strip()
        if len(value) == 7:
            value = value + "-01"
        return pd.to_datetime(value, errors="coerce")

    observations["date_sort"] = observations["observation_date"].apply(parse_observation_date)
    observations["source_url"] = observations["source_url"].astype(str)
    # Optional structured consultation measures; blanks remain missing, never zero.
    for column in [
        "support_pct", "oppose_pct", "conditional_support_pct", "unsure_pct",
        "response_count", "survey_count", "written_submissions", "engagement_count", "page_views"
    ]:
        if column in observations.columns:
            observations[column] = pd.to_numeric(observations[column], errors="coerce")
    return observations.sort_values(["date_sort", "issue"], ascending=[False, True])


@st.cache_data
def load_news_articles():
    """Load article metadata and reviewer annotations; no automated sentiment scores."""
    if not NEWS_PATH.exists():
        return pd.DataFrame()
    articles = pd.read_csv(NEWS_PATH, keep_default_na=False)
    required = {
        "article_id", "title", "publisher", "published_at", "source_url",
        "summary", "geography_match", "geography_review", "issue_suggested",
        "issue_reviewed", "article_tone", "public_sentiment_evidence",
        "review_status"
    }
    missing = required.difference(articles.columns)
    if missing:
        st.error("The news CSV is missing required columns: " + ", ".join(sorted(missing)))
        return pd.DataFrame()
    # Add candidate review fields when opening older local CSV snapshots.
    candidate_fields = {
        "candidate_mentions_suggested": "",
        "candidate_mentions_reviewed": "",
        "candidate_evidence_type": "Not assessed",
        "candidate_public_view_summary": "",
    }
    for column, default in candidate_fields.items():
        if column not in articles.columns:
            articles[column] = default
    articles["published_sort"] = pd.to_datetime(
        articles["published_at"], errors="coerce", utc=True
    )
    return articles.sort_values(
        ["published_sort", "title"], ascending=[False, True], na_position="last"
    )


@st.cache_data
def load_kew_candidates():
    if not KEW_CANDIDATES_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(KEW_CANDIDATES_PATH, keep_default_na=False).sort_values("ballot_order")


@st.cache_data
def load_kew_historical_results():
    if not KEW_RESULTS_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(KEW_RESULTS_PATH, keep_default_na=False)


@st.cache_data
def load_kew_polls():
    if not KEW_POLLS_PATH.exists():
        return pd.DataFrame()
    polls = pd.read_csv(KEW_POLLS_PATH, keep_default_na=False)
    for column in ["reported_pct", "alternate_reported_pct", "sample_size"]:
        if column in polls.columns:
            polls[column] = pd.to_numeric(polls[column], errors="coerce")
    return polls


@st.cache_data
def load_kew_external_forecast():
    if not KEW_EXTERNAL_FORECAST_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(KEW_EXTERNAL_FORECAST_PATH, keep_default_na=False)


@st.cache_data
def load_kew_external_2cp():
    if not KEW_EXTERNAL_2CP_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(KEW_EXTERNAL_2CP_PATH, keep_default_na=False)


@st.cache_data
def load_vic_poll_average_benchmark():
    if not VIC_POLL_AVERAGE_BENCHMARK_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(VIC_POLL_AVERAGE_BENCHMARK_PATH, keep_default_na=False)


DISTRICTS, HAS_DISTRICT_REGISTER = load_districts()
OBSERVATIONS = load_observations()
NEWS_ARTICLES = load_news_articles()
KEW_CANDIDATES = load_kew_candidates()
KEW_HISTORICAL_RESULTS = load_kew_historical_results()
KEW_POLLS = load_kew_polls()
KEW_EXTERNAL_FORECAST = load_kew_external_forecast()
KEW_EXTERNAL_2CP = load_kew_external_2cp()
VIC_POLL_AVERAGE_BENCHMARK = load_vic_poll_average_benchmark()

st.title("Australian Electoral Sentiment Tracker")
st.caption("Research prototype · Victoria 2026 live case · Federal and NSW expansion planned")

with st.sidebar:
    st.header("Explore")
    jurisdiction = st.selectbox("Jurisdiction", ["Victoria", "Federal", "NSW"])

    if jurisdiction == "Victoria":
        level = st.radio("Chamber", ["Legislative Assembly", "Legislative Council"])
        if level == "Legislative Assembly":
            district_names = DISTRICTS["district"].dropna().astype(str).tolist()
            electorate_options = ["All districts"] + district_names
            # Open on the Kew pilot so its seed observations are visible immediately.
            default_electorate_index = electorate_options.index("Kew") if "Kew" in electorate_options else 0
            district = st.selectbox("Electorate", electorate_options, index=default_electorate_index)
        else:
            district = st.selectbox(
                "Region",
                [
                    "All regions", "Eastern Victoria", "North-Eastern Metropolitan",
                    "Northern Metropolitan", "Northern Victoria",
                    "South-Eastern Metropolitan", "Southern Metropolitan",
                    "Western Metropolitan", "Western Victoria"
                ],
            )
    else:
        st.info("Federal and NSW electorate registers are planned next.")
        district = "All electorates"

    metric = st.selectbox(
        "Research view",
        [
            "Election baseline", "Issue sentiment", "Political discussion",
            "Search interest", "News coverage", "Economic context", "Data quality"
        ],
    )

if jurisdiction == "Victoria":
    st.subheader("Victoria · 2026 State Election")
    st.write(
        "Election day: **28 November 2026** · 88 Legislative Assembly districts · "
        "8 Legislative Council regions"
    )

    if level == "Legislative Assembly":
        selected_observations = OBSERVATIONS.copy()
        if district != "All districts":
            selected_observations = selected_observations[
                selected_observations["electorate"].str.casefold() == district.casefold()
            ]

        obs_count = len(selected_observations)
        direct_count = (
            selected_observations["evidence_class"].eq("direct_resident_feedback").sum()
            if obs_count else 0
        )
        issue_count = selected_observations["issue"].nunique() if obs_count else 0

        a, b, c, d = st.columns(4)
        a.metric("Districts in register", "88")
        b.metric("Last state election", "2022")
        c.metric("Current campaign", "2026")
        d.metric("Loaded observations", str(obs_count))

        if not HAS_DISTRICT_REGISTER:
            st.warning(
                "The district-register CSV is not present in this repository checkout. "
                "The Kew pilot remains available; add data/vic_districts_2026.csv to "
                "restore the full district selector."
            )

        if district == "All districts":
            st.markdown("#### District register")
            st.dataframe(DISTRICTS, use_container_width=True, hide_index=True)
            st.info(
                "The current seed observations are for Kew only. Select Kew in the sidebar "
                "to inspect them. No other district is assigned Kew's observations."
            )
        else:
            row_matches = DISTRICTS.loc[DISTRICTS["district"].astype(str) == district]
            vec_url = (
                row_matches.iloc[0].get("vec_url", "")
                if not row_matches.empty
                else "https://vec.vic.gov.au/electoral-boundaries/state-districts"
            )
            st.markdown(f"### {district}")
            st.markdown(f"[2026 district information at the VEC]({vec_url})")

            if district == "Kew":
                st.markdown("#### 2026 candidate register")
                st.caption(
                    "Official VEC nomination list, shown in ballot-paper order. "
                    "Candidate inclusion is descriptive and does not imply an assessment."
                )
                if not KEW_CANDIDATES.empty:
                    candidate_display = KEW_CANDIDATES[
                        ["ballot_order", "candidate_name", "party", "candidate_source_url"]
                    ].rename(columns={
                        "ballot_order": "Ballot order",
                        "candidate_name": "Candidate",
                        "party": "Party / affiliation",
                        "candidate_source_url": "VEC nominations",
                    })
                    st.dataframe(
                        candidate_display,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "VEC nominations": st.column_config.LinkColumn(
                                "Official VEC list", display_text="Open nominations ↗"
                            )
                        },
                    )
                else:
                    st.warning("The Kew candidate register is not present in data/.")

                st.markdown("#### 2022 historical result — baseline only")
                st.caption(
                    "These are actual results from the previous state election, not estimates "
                    "for 2026. Candidate names and the contest for the final preference "
                    "distribution differ from the current election."
                )
                if not KEW_HISTORICAL_RESULTS.empty:
                    historical_primary = KEW_HISTORICAL_RESULTS[
                        KEW_HISTORICAL_RESULTS["result_measure"] == "primary"
                    ].copy()
                    if not historical_primary.empty:
                        historical_primary["share_pct"] = pd.to_numeric(
                            historical_primary["share_pct"], errors="coerce"
                        )
                        st.dataframe(
                            historical_primary[
                                ["candidate_name", "party", "votes", "share_pct"]
                            ].rename(columns={
                                "candidate_name": "2022 candidate",
                                "party": "Party",
                                "votes": "First-preference votes",
                                "share_pct": "First preference (%)",
                            }).sort_values("First preference (%)", ascending=False),
                            use_container_width=True,
                            hide_index=True,
                        )
                    final_pair = KEW_HISTORICAL_RESULTS[
                        KEW_HISTORICAL_RESULTS["result_measure"] == "final_preference_distribution"
                    ].copy()
                    if not final_pair.empty:
                        st.markdown("**2022 final two-candidate preference distribution**")
                        st.dataframe(
                            final_pair[
                                ["candidate_name", "party", "votes", "share_pct"]
                            ].rename(columns={
                                "candidate_name": "2022 candidate",
                                "party": "Party",
                                "votes": "Votes after preferences",
                                "share_pct": "Share (%)",
                            }),
                            use_container_width=True,
                            hide_index=True,
                        )
                    st.caption(
                        "Source: Victorian Electoral Commission. In 2022 the final distribution "
                        "was Liberal candidate Jess Wilson versus Labor candidate Lucy Skelton. "
                        "The earlier booth-level two-candidate count was not the final distribution."
                    )
                else:
                    st.warning("The verified Kew 2022 result file is missing.")

            if RESULTS_PATH.exists():
                results = pd.read_csv(RESULTS_PATH)
                subset = results[
                    results.astype(str).apply(
                        lambda col: col.str.contains(district, case=False, na=False)
                    ).any(axis=1)
                ]
                if not subset.empty:
                    st.markdown("#### Historical election results")
                    st.dataframe(subset, use_container_width=True, hide_index=True)
                else:
                    st.info(
                        "The historical results file exists, but this district was not "
                        "matched automatically. Verify the source field mapping."
                    )
            else:
                st.info("District-level 2022 results have not yet been imported.")

            if district == "Kew":
                st.markdown("#### Published Kew polling measurements")
                if not KEW_POLLS.empty:
                    poll_meta = KEW_POLLS.iloc[0]
                    st.caption(
                        f"{poll_meta['pollster']} · {poll_meta['fieldwork_period']} · "
                        f"n={int(poll_meta['sample_size']) if str(poll_meta['sample_size']).strip() else 'not stated'} · "
                        f"published {poll_meta['publication_date']} · commissioned by {poll_meta['commissioned_by']}"
                    )
                    poll_columns = [
                        column for column in [
                            "option_label", "party_or_type", "reported_pct",
                            "alternate_reported_pct"
                        ] if column in KEW_POLLS.columns
                    ]
                    poll_display = KEW_POLLS[poll_columns].rename(columns={
                        "option_label": "Reported option",
                        "party_or_type": "Party / type",
                        "reported_pct": "Poll Bludger reported (%)",
                        "alternate_reported_pct": "Alternate media report (%)",
                    })
                    st.dataframe(
                        poll_display,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption(str(poll_meta["limitations"]))
                    st.markdown(
                        f"[Read the published poll report ↗]({poll_meta['source_url']})"
                    )
                else:
                    st.info("No published Kew seat-level poll has been loaded.")

            st.markdown("#### Campaign signals and expert analysis")
            st.caption(
                "These are separate indicators of campaign resources, campaign effort, "
                "statewide market expectations and published electoral analysis. None is "
                "treated as a direct measure of Kew voter preference."
            )

            donation_tab, activity_tab, market_tab, analyst_tab = st.tabs([
                "Disclosed donations", "Campaign presence", "Kalshi market", "Antony Green"
            ])

            with donation_tab:
                st.markdown("##### Publicly disclosed campaign donations")
                st.markdown(
                    f"[Open the VEC public disclosure register ↗]({VEC_DISCLOSURES_URL})"
                )
                st.caption(
                    "Victoria's 2026 disclosure threshold is $1,290 and disclosure is generally "
                    "required within 21 days. This ledger only captures disclosed entries; "
                    "small donations and not-yet-disclosed donations are not visible. "
                    "We do not store individual donor names in this tracker."
                )
                donation_data = load_csv_or_empty(
                    KEW_DONATIONS_PATH, DONATION_FIELDS
                )
                if not donation_data.empty:
                    donation_data["amount_aud"] = pd.to_numeric(
                        donation_data["amount_aud"], errors="coerce"
                    )
                    d1, d2, d3 = st.columns(3)
                    d1.metric(
                        "Disclosed amount captured",
                        f"${donation_data['amount_aud'].sum(skipna=True):,.0f}"
                    )
                    d2.metric("Disclosure records", len(donation_data))
                    d3.metric(
                        "Recipients",
                        donation_data["recipient_name"].nunique()
                    )
                    by_recipient = (
                        donation_data.dropna(subset=["amount_aud"])
                        .groupby("recipient_name")["amount_aud"]
                        .sum()
                        .sort_values(ascending=False)
                    )
                    if not by_recipient.empty:
                        st.bar_chart(by_recipient.rename("Disclosed amount (AUD)"))
                    donation_display = donation_data.sort_values(
                        "disclosure_date", ascending=False
                    )[
                        [
                            "donation_date", "disclosure_date", "electorate", "recipient_name",
                            "recipient_type", "donor_category", "amount_aud",
                            "geographic_scope", "source_url"
                        ]
                    ].rename(columns={
                        "donation_date": "Donation date",
                        "disclosure_date": "Disclosure date",
                        "recipient_name": "Recipient",
                        "recipient_type": "Recipient type",
                        "donor_category": "Donor category",
                        "amount_aud": "Amount (AUD)",
                        "geographic_scope": "Geographic scope",
                        "source_url": "Source",
                    })
                    st.dataframe(
                        donation_display,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Source": st.column_config.LinkColumn(
                                "Source", display_text="Open source ↗"
                            )
                        },
                    )
                else:
                    st.info(
                        "No donation disclosures have been entered yet. An empty ledger means "
                        "we have not captured records; it does not mean candidates received no donations."
                    )

                with st.expander("Record a VEC donation disclosure"):
                    candidate_options = (
                        KEW_CANDIDATES["candidate_name"].astype(str).tolist()
                        if not KEW_CANDIDATES.empty else []
                    )
                    with st.form("kew_add_donation_form"):
                        donation_electorate = st.selectbox(
                            "Electorate",
                            DISTRICTS["district"].astype(str).tolist(),
                            index=(DISTRICTS["district"].astype(str).tolist().index("Kew")
                                   if "Kew" in DISTRICTS["district"].astype(str).tolist() else 0),
                        )
                        donation_date_value = st.date_input(
                            "Donation date", value=LOCAL_TODAY, key="donation_date"
                        )
                        disclosure_date_value = st.date_input(
                            "Disclosure date", value=LOCAL_TODAY, key="disclosure_date"
                        )
                        donation_recipient = st.selectbox(
                            "Recipient",
                            candidate_options + [
                                "Liberal Party (statewide)",
                                "Australian Labor Party (statewide)",
                                "The Greens (statewide)",
                                "One Nation Victoria (statewide)",
                                "Other party / associated entity",
                                "Third-party campaigner",
                            ],
                        )
                        donation_type = st.selectbox(
                            "Recipient type",
                            [
                                "Kew candidate",
                                "Statewide political party",
                                "Associated entity",
                                "Third-party campaigner",
                            ],
                        )
                        donor_category = st.selectbox(
                            "Donor category (not donor name)",
                            [
                                "Individual",
                                "Company / business",
                                "Trade union",
                                "Association / community organisation",
                                "Political party / associated entity",
                                "Other / unclear",
                            ],
                        )
                        amount_value = st.number_input(
                            "Disclosed donation amount (AUD)",
                            min_value=1250.0,
                            value=1290.0,
                            step=100.0,
                            help=(
                                "The general disclosure threshold is $1,290. A $1,250 threshold "
                                "applied to the 15 April–9 June 2026 transition period. Only enter "
                                "records actually visible in the VEC public disclosure register."
                            ),
                        )
                        donation_scope = st.selectbox(
                            "Geographic scope",
                            [
                                "Kew candidate recipient",
                                "Statewide party / entity",
                                "Unknown / not seat-specific",
                            ],
                        )
                        donation_source = st.text_input(
                            "Source URL", value=VEC_DISCLOSURES_URL
                        )
                        donation_note = st.text_area(
                            "Evidence note (e.g. record date, donation type, VEC reference)"
                        )
                        donation_submitted = st.form_submit_button(
                            "Add disclosed donation"
                        )
                    if donation_submitted:
                        record_id = (
                            f"DON-{donation_date_value.isoformat()}-"
                            f"{len(donation_data) + 1:04d}-{abs(hash(donation_recipient)) % 10000:04d}"
                        )
                        append_csv_record(
                            KEW_DONATIONS_PATH,
                            {
                                "record_id": record_id,
                                "donation_date": donation_date_value.isoformat(),
                                "disclosure_date": disclosure_date_value.isoformat(),
                                "recipient_name": donation_recipient,
                                "recipient_type": donation_type,
                                "donor_category": donor_category,
                                "amount_aud": amount_value,
                                "geographic_scope": donation_scope,
                                "source_url": donation_source,
                                "source_note": donation_note,
                                "recorded_at": sydney_now(),
                                "electorate": donation_electorate,
                            },
                            DONATION_FIELDS,
                        )
                        st.success(
                            "Donation record added locally. Commit "
                            "data/kew_campaign_donations.csv to preserve it in GitHub."
                        )
                        st.rerun()

            with activity_tab:
                st.markdown("##### Observable campaign presence")
                st.caption(
                    "Record one row per distinct event or observation. Separate scheduled events "
                    "from campaign-reported completions and independent observations. Volunteer "
                    "and door-contact counts are stored only when a source reports them; do not "
                    "estimate counts from photographs or treat attendance as voter support."
                )
                activity_data = load_csv_or_empty(
                    KEW_ACTIVITY_PATH, ACTIVITY_FIELDS
                )
                if not activity_data.empty:
                    a1, a2, a3 = st.columns(3)
                    a1.metric("Activity records", len(activity_data))
                    a2.metric(
                        "Candidates / groups represented",
                        activity_data["candidate_name"].nunique()
                    )
                    a3.metric(
                        "Completed or observed records",
                        int(activity_data["activity_status"].isin([
                            "Campaign-reported completed",
                            "Independently observed",
                            "Third-party reported",
                        ]).sum())
                    )
                    presence_counts = (
                        activity_data.groupby(
                            ["candidate_name", "activity_type"]
                        ).size().unstack(fill_value=0)
                    )
                    st.markdown("**Recorded activity by candidate and type**")
                    st.bar_chart(presence_counts)
                    activity_display = activity_data.sort_values(
                        "activity_date", ascending=False
                    )[
                        [
                            "activity_date", "electorate", "candidate_name", "party",
                            "activity_type", "activity_status", "location_suburb",
                            "volunteers_reported", "doors_contacted_reported",
                            "source_type", "source_url", "evidence_note"
                        ]
                    ].rename(columns={
                        "activity_date": "Activity date",
                        "candidate_name": "Candidate / group",
                        "party": "Party",
                        "activity_type": "Activity",
                        "activity_status": "Evidence status",
                        "location_suburb": "Suburb",
                        "volunteers_reported": "Volunteers (reported)",
                        "doors_contacted_reported": "Doors contacted (reported)",
                        "source_type": "Source type",
                        "source_url": "Source",
                        "evidence_note": "Evidence note",
                    })
                    st.dataframe(
                        activity_display,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Source": st.column_config.LinkColumn(
                                "Source", display_text="Open source ↗"
                            )
                        },
                    )
                else:
                    st.info(
                        "No campaign activity has been recorded yet. Missing observations do not "
                        "mean a candidate has no campaign activity."
                    )

                with st.expander("Record a campaign activity observation"):
                    with st.form("kew_add_activity_form"):
                        activity_electorate = st.selectbox(
                            "Electorate",
                            DISTRICTS["district"].astype(str).tolist(),
                            index=(DISTRICTS["district"].astype(str).tolist().index("Kew")
                                   if "Kew" in DISTRICTS["district"].astype(str).tolist() else 0),
                        )
                        activity_candidate = st.selectbox(
                            "Candidate / campaign",
                            candidate_options + ["Party / multi-candidate campaign"],
                        )
                        activity_party = (
                            str(KEW_CANDIDATES.loc[
                                KEW_CANDIDATES["candidate_name"] == activity_candidate,
                                "party"
                            ].iloc[0])
                            if not KEW_CANDIDATES.empty and activity_candidate in candidate_options
                            else "Multiple / statewide"
                        )
                        activity_date_value = st.date_input(
                            "Activity date", value=LOCAL_TODAY, key="campaign_activity_date"
                        )
                        activity_kind = st.selectbox(
                            "Activity type",
                            [
                                "Door-knocking session",
                                "Street stall",
                                "Shopping-strip visit",
                                "Community event / forum",
                                "Volunteer mobilisation",
                                "Campaign signage / material",
                                "Paid advertising / mail",
                                "Other campaign appearance",
                            ],
                        )
                        activity_status = st.selectbox(
                            "What does the evidence establish?",
                            [
                                "Scheduled / announced",
                                "Campaign-reported completed",
                                "Independently observed",
                                "Third-party reported",
                            ],
                        )
                        activity_suburb = st.text_input("Suburb / locality")
                        activity_location = st.text_input(
                            "Specific location (optional)"
                        )
                        volunteers_value = st.text_input(
                            "Volunteers present (exact reported number; optional)"
                        )
                        doors_value = st.text_input(
                            "Doors contacted (exact reported number; optional)"
                        )
                        activity_source_type = st.selectbox(
                            "Source type",
                            [
                                "Candidate / campaign post",
                                "Local news / media report",
                                "Personally observed",
                                "Other public source",
                            ],
                        )
                        activity_source_url = st.text_input("Source URL")
                        activity_note = st.text_area(
                            "Evidence note (what happened, who reported it, and what remains unknown)"
                        )
                        activity_submitted = st.form_submit_button(
                            "Add campaign activity"
                        )
                    if activity_submitted:
                        activity_id = (
                            f"ACT-{activity_date_value.isoformat()}-"
                            f"{len(activity_data) + 1:04d}"
                        )
                        append_csv_record(
                            KEW_ACTIVITY_PATH,
                            {
                                "activity_id": activity_id,
                                "activity_date": activity_date_value.isoformat(),
                                "recorded_at": sydney_now(),
                                "electorate": activity_electorate,
                                "candidate_name": activity_candidate,
                                "party": activity_party,
                                "activity_type": activity_kind,
                                "activity_status": activity_status,
                                "location_suburb": activity_suburb,
                                "location_detail": activity_location,
                                "volunteers_reported": volunteers_value.strip(),
                                "doors_contacted_reported": doors_value.strip(),
                                "source_type": activity_source_type,
                                "source_url": activity_source_url,
                                "evidence_note": activity_note,
                            },
                            ACTIVITY_FIELDS,
                        )
                        st.success(
                            "Campaign activity added locally. Commit "
                            "data/kew_campaign_activity.csv to preserve it in GitHub."
                        )
                        st.rerun()

            with market_tab:
                st.markdown("##### Kalshi — Victorian state election market")
                st.markdown(
                    f"[Open the Kalshi market ↗]({KALSHI_EVENT_URL})"
                )
                st.caption(
                    "This market concerns which party or coalition wins the most seats in "
                    "the Victorian Legislative Assembly. It is a statewide signal, not a Kew "
                    "candidate market. The tracker records individual contract bid/ask prices, "
                    "last trade and liquidity; it does not force separate contract prices to sum to 100%."
                )
                if st.button(
                    "Fetch and record latest Kalshi prices",
                    key="fetch_kalshi_market_data",
                ):
                    try:
                        kalshi_markets = fetch_kalshi_event_markets(
                            KALSHI_EVENT_TICKER
                        )
                        market_rows = kalshi_market_snapshot_rows(
                            kalshi_markets, KALSHI_EVENT_TICKER
                        )
                        for market_row in market_rows:
                            append_csv_record(
                                KALSHI_SNAPSHOTS_PATH,
                                market_row,
                                KALSHI_MARKET_FIELDS,
                            )
                        st.success(
                            f"Recorded {len(market_rows)} Kalshi market contracts. "
                            "Commit data/kalshi_market_snapshots.csv to preserve the history."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(
                            f"Kalshi data could not be retrieved: {type(exc).__name__}: {exc}"
                        )

                market_data = load_csv_or_empty(
                    KALSHI_SNAPSHOTS_PATH, KALSHI_MARKET_FIELDS
                )
                if not market_data.empty:
                    for column in [
                        "implied_chance_pct", "yes_bid_dollars", "yes_ask_dollars",
                        "last_price_dollars", "bid_ask_spread_cents",
                        "volume", "volume_24h", "open_interest", "liquidity_dollars"
                    ]:
                        market_data[column] = pd.to_numeric(
                            market_data[column], errors="coerce"
                        )
                    market_data["snapshot_at_parsed"] = pd.to_datetime(
                        market_data["snapshot_at"], errors="coerce"
                    )
                    latest_markets = (
                        market_data.dropna(subset=["snapshot_at_parsed"])
                        .sort_values("snapshot_at_parsed")
                        .groupby("market_ticker", as_index=False)
                        .tail(1)
                        .sort_values("market_outcome")
                    )
                    m1, m2 = st.columns(2)
                    m1.metric("Market contracts tracked", len(latest_markets))
                    m2.metric(
                        "Last market snapshot",
                        market_data["snapshot_at"].max()[:16].replace("T", " ")
                    )
                    current_market_display = latest_markets[
                        [
                            "market_outcome", "implied_chance_pct",
                            "yes_bid_dollars", "yes_ask_dollars",
                            "bid_ask_spread_cents", "volume", "volume_24h",
                            "open_interest"
                        ]
                    ].rename(columns={
                        "market_outcome": "Outcome",
                        "implied_chance_pct": "Midpoint / last price (%)",
                        "yes_bid_dollars": "YES bid ($)",
                        "yes_ask_dollars": "YES ask ($)",
                        "bid_ask_spread_cents": "Spread (¢)",
                        "volume": "Total volume",
                        "volume_24h": "24h volume",
                        "open_interest": "Open interest",
                    })
                    st.dataframe(
                        current_market_display,
                        use_container_width=True,
                        hide_index=True,
                    )
                    market_history = market_data.dropna(
                        subset=["snapshot_at_parsed", "implied_chance_pct"]
                    ).pivot_table(
                        index="snapshot_at_parsed",
                        columns="market_outcome",
                        values="implied_chance_pct",
                        aggfunc="last",
                    )
                    if not market_history.empty:
                        st.line_chart(market_history)
                    st.caption(
                        "Market price is a traded-market expectation, not a poll. A wide spread, "
                        "low volume or low open interest indicates limited liquidity. Historical "
                        "prices are only available from the first snapshot recorded by this tracker."
                    )
                else:
                    st.info(
                        "No Kalshi price snapshots have been recorded. Fetch the latest public "
                        "market data to establish the first observation."
                    )

            with analyst_tab:
                st.markdown("##### Antony Green and electoral analysis")
                st.caption(
                    "Curated notes preserve an analyst's published date, source and interpretation "
                    "limits. These are analyst references, not automated polling data or a vote forecast."
                )
                analyst_data = load_csv_or_empty(
                    ANTONY_GREEN_NOTES_PATH, ANALYST_FIELDS
                )
                if not analyst_data.empty:
                    analyst_display = analyst_data.sort_values(
                        "published_date", ascending=False
                    )[
                        [
                            "published_date", "analyst", "title", "coverage",
                            "analysis_type", "key_points", "interpretation_limit",
                            "source_url"
                        ]
                    ].rename(columns={
                        "published_date": "Published",
                        "analyst": "Analyst",
                        "title": "Article / analysis",
                        "coverage": "Coverage",
                        "analysis_type": "Type",
                        "key_points": "Key points",
                        "interpretation_limit": "Interpretation limit",
                        "source_url": "Source",
                    })
                    st.dataframe(
                        analyst_display,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Source": st.column_config.LinkColumn(
                                "Source", display_text="Read analysis ↗"
                            )
                        },
                    )
                else:
                    st.info("No analyst notes have been recorded.")

                with st.expander("Add an analyst article or update"):
                    with st.form("kew_add_analyst_note_form"):
                        analyst_name = st.text_input(
                            "Analyst / source", value="Antony Green"
                        )
                        analyst_date = st.date_input(
                            "Publication date", value=LOCAL_TODAY, key="analyst_date"
                        )
                        analyst_title = st.text_input("Article title")
                        analyst_coverage = st.selectbox(
                            "Geographic coverage",
                            [
                                "Kew electorate",
                                "Victoria statewide",
                                "Multiple Victorian electorates",
                                "National / other",
                            ],
                        )
                        analyst_type = st.selectbox(
                            "Analysis type",
                            [
                                "Electoral pendulum / historical margin",
                                "Preference flow analysis",
                                "District-level geographic analysis",
                                "Candidate-field analysis",
                                "Polling analysis",
                                "Election system / count methodology",
                                "Other expert commentary",
                            ],
                        )
                        analyst_points = st.text_area("Key points from the article")
                        analyst_limit = st.text_area(
                            "How should this evidence be interpreted / limited?"
                        )
                        analyst_url = st.text_input("Source URL")
                        analyst_submitted = st.form_submit_button(
                            "Add analyst reference"
                        )
                    if analyst_submitted:
                        analyst_id = (
                            f"ANL-{analyst_date.isoformat()}-"
                            f"{len(analyst_data) + 1:04d}"
                        )
                        append_csv_record(
                            ANTONY_GREEN_NOTES_PATH,
                            {
                                "record_id": analyst_id,
                                "published_date": analyst_date.isoformat(),
                                "analyst": analyst_name,
                                "title": analyst_title,
                                "coverage": analyst_coverage,
                                "analysis_type": analyst_type,
                                "key_points": analyst_points,
                                "interpretation_limit": analyst_limit,
                                "source_url": analyst_url,
                                "review_status": "Manually reviewed",
                                "recorded_at": sydney_now(),
                            },
                            ANALYST_FIELDS,
                        )
                        st.success(
                            "Analyst reference added locally. Commit "
                            "data/antony_green_notes.csv to preserve it in GitHub."
                        )
                        st.rerun()

            st.markdown("#### Polling trends and Kew forecast workspace")
            st.caption(
                "This is an exploratory research model. It separates published poll results, "
                "modelled scenarios and external forecasts. It is not yet calibrated against "
                "historical forecast errors."
            )

            if not VIC_STATE_POLLS_PATH.exists():
                st.warning("The statewide polling ledger is missing.")
            else:
                try:
                    state_average = calculate_statewide_poll_average(
                        VIC_STATE_POLLS_PATH,
                        as_of=LOCAL_TODAY,
                        half_life_days=14,
                    )
                    poll_history = pd.read_csv(VIC_STATE_POLLS_PATH, keep_default_na=False)
                    for column in [
                        "alp_pct", "coalition_pct", "one_nation_pct",
                        "greens_pct", "others_pct", "coalition_tpp_pct",
                        "sample_size"
                    ]:
                        poll_history[column] = pd.to_numeric(
                            poll_history[column], errors="coerce"
                        )
                    poll_history["fieldwork_end"] = pd.to_datetime(
                        poll_history["fieldwork_end"], errors="coerce"
                    )
                    poll_history = poll_history.sort_values("fieldwork_end")

                    st.markdown("##### Victorian statewide primary-vote trend")
                    trend_columns = [
                        "alp_pct", "coalition_pct", "one_nation_pct",
                        "greens_pct", "others_pct"
                    ]
                    trend_data = (
                        poll_history.dropna(subset=["fieldwork_end"])
                        .set_index("fieldwork_end")[trend_columns]
                        .rename(columns={
                            "alp_pct": "Labor",
                            "coalition_pct": "Coalition",
                            "one_nation_pct": "One Nation",
                            "greens_pct": "Greens",
                            "others_pct": "Others",
                        })
                    )
                    st.line_chart(trend_data)
                    st.caption(
                        "Each point is a published poll, not a weekly opinion measure. "
                        "Excluded and superseded polls remain visible in the trend history, "
                        "but are not all used in the current weighted average."
                    )

                    average = state_average["primary_average"]
                    avg_cols = st.columns(5)
                    for col, label, key in zip(
                        avg_cols,
                        ["Labor", "Coalition", "One Nation", "Greens", "Others"],
                        ["Labor", "Liberal–National Coalition", "One Nation", "Greens", "Others"],
                    ):
                        col.metric(label, f"{average[key]:.1f}%")
                    if state_average["coalition_tpp_average"] is not None:
                        st.metric(
                            "Weighted statewide Coalition–Labor two-party-preferred (2PP) average",
                            f"{state_average['coalition_tpp_average']:.1f}%",
                            help="Calculated only from eligible statewide polls that published a Coalition–Labor 2PP figure; this is not Kew 2CP.",
                        )

                    st.markdown("##### Our polling average versus an external benchmark")
                    comparison_rows = [
                        {
                            "Party": party,
                            "Our weighted average (%)": value,
                            "Earth Elects benchmark (%)": (
                                float(VIC_POLL_AVERAGE_BENCHMARK.iloc[0][column])
                                if not VIC_POLL_AVERAGE_BENCHMARK.empty else None
                            ),
                        }
                        for party, column, value in [
                            ("Labor", "alp_pct", average["Labor"]),
                            ("Coalition", "coalition_pct", average["Liberal–National Coalition"]),
                            ("One Nation", "one_nation_pct", average["One Nation"]),
                            ("Greens", "greens_pct", average["Greens"]),
                            ("Others", "others_pct", average["Others"]),
                        ]
                    ]
                    st.dataframe(
                        pd.DataFrame(comparison_rows),
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption(
                        state_average["method"] +
                        " Our pollster quality weights are provisional project assumptions. "
                        "The external average is shown for comparison, not blended into our calculation."
                    )

                    with st.expander("Poll ledger and source records"):
                        display_polls = poll_history[
                            [
                                "pollster", "fieldwork_start", "fieldwork_end",
                                "sample_size", "mode", "sample_frame",
                                "recruitment_method", "weighting", "response_rate",
                                "effective_sample_size", "reported_margin_of_error",
                                "quality_weight", "alp_pct", "coalition_pct",
                                "one_nation_pct", "greens_pct", "others_pct",
                                "coalition_tpp_pct", "average_eligible", "source_url"
                            ]
                        ].rename(columns={
                            "pollster": "Pollster",
                            "fieldwork_start": "Fieldwork start",
                            "fieldwork_end": "Fieldwork end",
                            "sample_size": "Sample",
                            "mode": "Mode",
                            "sample_frame": "Sample frame",
                            "recruitment_method": "Recruitment",
                            "weighting": "Weighting",
                            "response_rate": "Response rate",
                            "effective_sample_size": "Effective sample",
                            "reported_margin_of_error": "Reported MOE",
                            "quality_weight": "Project source weight",
                            "alp_pct": "Labor",
                            "coalition_pct": "Coalition",
                            "one_nation_pct": "One Nation",
                            "greens_pct": "Greens",
                            "others_pct": "Others",
                            "coalition_tpp_pct": "Coalition 2PP",
                            "average_eligible": "In our average",
                            "source_url": "Source",
                        })
                        st.caption(
                            "Methodology fields marked 'Not reported' are genuine disclosure gaps "
                            "in the sources reviewed, not values assumed by the tracker. "
                            "Project source weights are transparent modelling assumptions, not a "
                            "statistical quality rating."
                        )
                        st.dataframe(
                            display_polls,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Source": st.column_config.LinkColumn(
                                    "Source", display_text="Open source ↗"
                                )
                            },
                        )
                        methodology_path = DATA_DIR / "polling_methodology_notes.csv"
                        if methodology_path.exists():
                            methodology_notes = pd.read_csv(
                                methodology_path, keep_default_na=False
                            )
                            st.markdown("**Background on polling methodology**")
                            st.dataframe(
                                methodology_notes[
                                    [
                                        "study_date", "source", "method_issue",
                                        "summary", "interpretation_limit", "source_url"
                                    ]
                                ].rename(columns={
                                    "study_date": "Date",
                                    "source": "Source",
                                    "method_issue": "Issue",
                                    "summary": "Finding",
                                    "interpretation_limit": "Limit",
                                    "source_url": "Reference",
                                }),
                                use_container_width=True,
                                hide_index=True,
                                column_config={
                                    "Reference": st.column_config.LinkColumn(
                                        "Reference", display_text="Read reference ↗"
                                    )
                                },
                            )

                    st.markdown("##### Kew candidate first-preference scenario")
                    pass_through = st.slider(
                        "Apply this fraction of statewide polling movement to Kew candidates",
                        min_value=0.0,
                        max_value=1.5,
                        value=1.0,
                        step=0.1,
                        help=(
                            "1.0 applies the full change between the March Resolve state poll "
                            "and our current weighted statewide average to the matching Kew party "
                            "candidates. 0.0 holds their March/local or historical anchors unchanged. "
                            "This is a scenario control, not a statistically fitted parameter."
                        ),
                        key="kew_poll_swing_passthrough",
                    )
                    candidate_scenario = build_kew_candidate_scenario(
                        KEW_CANDIDATES_PATH,
                        KEW_RESULTS_PATH,
                        KEW_POLLS_PATH,
                        state_average,
                        VIC_STATE_POLLS_PATH,
                        pass_through=pass_through,
                    )
                    low_scenario = build_kew_candidate_scenario(
                        KEW_CANDIDATES_PATH,
                        KEW_RESULTS_PATH,
                        KEW_POLLS_PATH,
                        state_average,
                        VIC_STATE_POLLS_PATH,
                        pass_through=0.5,
                    )
                    high_scenario = build_kew_candidate_scenario(
                        KEW_CANDIDATES_PATH,
                        KEW_RESULTS_PATH,
                        KEW_POLLS_PATH,
                        state_average,
                        VIC_STATE_POLLS_PATH,
                        pass_through=1.5,
                    )
                    low_map = dict(zip(
                        low_scenario["candidate_name"], low_scenario["primary_estimate_pct"]
                    ))
                    high_map = dict(zip(
                        high_scenario["candidate_name"], high_scenario["primary_estimate_pct"]
                    ))
                    candidate_scenario["sensitivity_low_pct"] = candidate_scenario[
                        "candidate_name"
                    ].map({
                        name: min(
                            value,
                            high_map.get(name) if pd.notna(high_map.get(name)) else value,
                        )
                        for name, value in low_map.items()
                        if pd.notna(value)
                    })
                    candidate_scenario["sensitivity_high_pct"] = candidate_scenario[
                        "candidate_name"
                    ].map({
                        name: max(
                            value,
                            high_map.get(name) if pd.notna(high_map.get(name)) else value,
                        )
                        for name, value in low_map.items()
                        if pd.notna(value)
                    })

                    candidate_chart = candidate_scenario.dropna(
                        subset=["primary_estimate_pct"]
                    ).set_index("candidate_name")[["primary_estimate_pct"]]
                    candidate_chart = candidate_chart.rename(
                        columns={"primary_estimate_pct": "Scenario first preference (%)"}
                    )
                    st.bar_chart(candidate_chart)
                    candidate_display = candidate_scenario[
                        [
                            "candidate_name", "party", "primary_estimate_pct",
                            "sensitivity_low_pct", "sensitivity_high_pct",
                            "estimate_status", "estimate_basis"
                        ]
                    ].rename(columns={
                        "candidate_name": "Candidate",
                        "party": "Party",
                        "primary_estimate_pct": "Scenario estimate (%)",
                        "sensitivity_low_pct": "Sensitivity low (%)",
                        "sensitivity_high_pct": "Sensitivity high (%)",
                        "estimate_status": "Status",
                        "estimate_basis": "Basis / limitation",
                    })
                    st.dataframe(
                        candidate_display,
                        use_container_width=True,
                        hide_index=True,
                    )

                    # Compare observed checkpoints with the current scenario, without
                    # pretending that unlike candidate contests are directly equivalent.
                    historical_primary = KEW_HISTORICAL_RESULTS[
                        KEW_HISTORICAL_RESULTS["result_measure"] == "primary"
                    ].copy()
                    historical_by_name = dict(zip(
                        historical_primary["candidate_name"],
                        pd.to_numeric(historical_primary["share_pct"], errors="coerce")
                    ))
                    march_by_name = {
                        "Jess Wilson": 38.0,
                        "Sophie Torney": 17.0,
                        "David Sun": 13.5,
                        "David Laird": 13.0,
                    }
                    comparison_map = {
                        "Jess Wilson": ("Jess Wilson", "direct poll anchor"),
                        "Sophie Torney": ("Sophie Torney", "direct poll anchor"),
                        "David Sun": ("Lucy Skelton", "2022 Labor candidate proxy; March poll is party-only"),
                        "David Laird": (None, "March poll is One Nation party-only; candidate not yet selected"),
                        "Jackie Carter": ("Jackie Carter", "same party/candidate"),
                        "Ann Seeley": ("Ann Seeley", "same candidate"),
                        "Juliet Hales": ("Ruby Schofield", "same party proxy"),
                        "Samantha Lincolne": (None, "statewide party proxy"),
                        "Finlay Davis": ("Finlay Davis", "same candidate"),
                        "Man Liang": (None, "no candidate-specific baseline"),
                    }
                    comparison_rows = []
                    for _, item in candidate_scenario.iterrows():
                        name = item["candidate_name"]
                        if name == "Unallocated / unmodelled vote":
                            continue
                        historical_name, comparison_note = comparison_map.get(
                            name, (None, "no comparable baseline")
                        )
                        historical_value = (
                            historical_by_name.get(historical_name)
                            if historical_name else None
                        )
                        comparison_rows.append({
                            "Candidate": name,
                            "2022 Kew primary (%)": historical_value,
                            "March 2026 poll / party figure (%)": march_by_name.get(name),
                            "Current scenario (%)": item["primary_estimate_pct"],
                            "Comparison note": comparison_note,
                        })
                    st.markdown("##### Candidate vote checkpoints")
                    checkpoint_df = pd.DataFrame(comparison_rows)
                    checkpoint_chart = checkpoint_df.set_index("Candidate")[
                        [
                            "2022 Kew primary (%)",
                            "March 2026 poll / party figure (%)",
                            "Current scenario (%)",
                        ]
                    ]
                    st.bar_chart(checkpoint_chart)
                    st.dataframe(
                        checkpoint_df,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption(
                        "The March poll did not report every candidate. 2022 figures for a "
                        "different candidate of the same party are labelled as proxies. "
                        "Blank values mean no comparable measurement was found."
                    )

                    st.caption(
                        "Sensitivity low/high shows the effect of changing statewide polling "
                        "pass-through from 0.5× to 1.5×. It is not a statistical confidence interval. "
                        "Man Liang is not separately estimated; the unallocated residual includes "
                        "his possible vote and all other unmodelled/unreported vote."
                    )

                    st.markdown("##### Conditional Wilson–Sun two-candidate-preferred (2CP) scenario")
                    swing_multiplier = st.slider(
                        "Kew uniform-swing multiplier",
                        min_value=0.5,
                        max_value=1.5,
                        value=1.0,
                        step=0.1,
                        help="1.0 applies the full statewide Coalition 2PP share change to the 2022 Kew Liberal–Labor final distribution.",
                        key="kew_uniform_swing_multiplier",
                    )
                    tpp_scenario = calculate_kew_labor_coalition_scenario(
                        state_average, uniform_swing_multiplier=swing_multiplier
                    )
                    if tpp_scenario.get("available"):
                        t1, t2, t3 = st.columns(3)
                        t1.metric(
                            "Jess Wilson (Liberal)",
                            f"{tpp_scenario['coalition_share_pct']:.1f}%"
                        )
                        t2.metric(
                            "David Sun (Labor)",
                            f"{tpp_scenario['labor_share_pct']:.1f}%"
                        )
                        t3.metric(
                            "Scenario margin",
                            f"{tpp_scenario['coalition_share_pct'] - tpp_scenario['labor_share_pct']:.1f} pts"
                        )
                        st.caption(
                            "Conditional 2CP scenario only: assumes Wilson and Sun are the final two, "
                            "and applies a uniform statewide two-party swing to Kew's 2022 final "
                            "preference distribution. The actual final two could include Sophie Torney "
                            "or David Laird, in which case this is not the relevant count."
                        )
                        st.caption(
                            f"Sensitivity at 0.5×–1.5× statewide movement: "
                            f"{tpp_scenario['sensitivity_low_pct']:.1f}%–"
                            f"{tpp_scenario['sensitivity_high_pct']:.1f}% for Wilson. "
                            "This is a scenario range, not a confidence interval."
                        )

                    if not KEW_EXTERNAL_FORECAST.empty:
                        st.markdown("##### External Kew forecast benchmark")
                        st.caption(
                            "AEF's published forecast, last updated 30 October 2026. "
                            "This is a separate external model, not an output of our tracker."
                        )
                        ext = KEW_EXTERNAL_FORECAST.copy()
                        ext_display = ext[
                            [
                                "candidate_name", "party", "first_preference_median_pct",
                                "first_preference_low_pct", "first_preference_high_pct",
                                "win_probability_pct"
                            ]
                        ].rename(columns={
                            "candidate_name": "Candidate",
                            "party": "Party",
                            "first_preference_median_pct": "Primary median (%)",
                            "first_preference_low_pct": "Low range (%)",
                            "first_preference_high_pct": "High range (%)",
                            "win_probability_pct": "External win probability (%)",
                        })
                        st.dataframe(
                            ext_display,
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.markdown(
                            "[Open AEF's Kew forecast and methodology ↗]"
                            "(https://www.aeforecasts.com/seat/2026vic/regular/kew/)"
                        )

                    if not KEW_EXTERNAL_2CP.empty:
                        st.markdown("##### External final-two scenarios")
                        st.dataframe(
                            KEW_EXTERNAL_2CP[
                                [
                                    "scenario", "final_pair_candidate_a", "candidate_a_pct",
                                    "final_pair_candidate_b", "candidate_b_pct",
                                    "scenario_probability_pct"
                                ]
                            ].rename(columns={
                                "scenario": "Possible final pair",
                                "final_pair_candidate_a": "Candidate A",
                                "candidate_a_pct": "Candidate A (%)",
                                "final_pair_candidate_b": "Candidate B",
                                "candidate_b_pct": "Candidate B (%)",
                                "scenario_probability_pct": "Probability of this pair (%)",
                            }),
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.caption(
                            "These final-pair probabilities are AEF's published simulation outputs, "
                            "not our own estimates. Our tracker does not yet have enough Kew-specific "
                            "preference-flow evidence to make an independent final-two forecast."
                        )

                    st.markdown("##### Save and track forecast snapshots")
                    st.caption(
                        "Record a dated snapshot after reviewing the inputs. This lets us compare "
                        "what the model said on each date with later updates and the final result."
                    )
                    if st.button("Record today's Kew forecast snapshot", key="save_kew_forecast_snapshot"):
                        snapshot_date = LOCAL_TODAY.isoformat()
                        new_snapshot = make_snapshot_rows(
                            snapshot_date, candidate_scenario, tpp_scenario
                        )
                        if KEW_FORECAST_SNAPSHOTS_PATH.exists():
                            old_snapshots = pd.read_csv(
                                KEW_FORECAST_SNAPSHOTS_PATH, keep_default_na=False
                            )
                            old_snapshots = old_snapshots[
                                ~(
                                    (old_snapshots["snapshot_date"] == snapshot_date)
                                    & (old_snapshots["model_version"] == MODEL_VERSION)
                                )
                            ]
                            combined_snapshots = pd.concat(
                                [old_snapshots, new_snapshot], ignore_index=True
                            )
                        else:
                            combined_snapshots = new_snapshot
                        combined_snapshots.to_csv(
                            KEW_FORECAST_SNAPSHOTS_PATH, index=False
                        )
                        st.success(
                            "Forecast snapshot saved locally. Commit data/kew_forecast_snapshots.csv "
                            "to GitHub to preserve it in the repository."
                        )
                        st.rerun()

                    if KEW_FORECAST_SNAPSHOTS_PATH.exists():
                        snapshots = pd.read_csv(
                            KEW_FORECAST_SNAPSHOTS_PATH, keep_default_na=False
                        )
                        candidate_snapshots = snapshots[
                            snapshots["metric_type"] == "candidate_primary_scenario"
                        ].copy()
                        if not candidate_snapshots.empty:
                            snapshot_candidate_names = [
                                name for name in candidate_snapshots["candidate_name"].unique()
                                if name != "Unallocated / unmodelled vote"
                            ]
                            selected_snapshot_candidate = st.selectbox(
                                "Candidate forecast history",
                                snapshot_candidate_names,
                                key="kew_snapshot_candidate",
                            )
                            selected_history = candidate_snapshots[
                                candidate_snapshots["candidate_name"] == selected_snapshot_candidate
                            ].copy()
                            selected_history["estimate_pct"] = pd.to_numeric(
                                selected_history["estimate_pct"], errors="coerce"
                            )
                            selected_history["snapshot_date"] = pd.to_datetime(
                                selected_history["snapshot_date"], errors="coerce"
                            )
                            st.line_chart(
                                selected_history.set_index("snapshot_date")[["estimate_pct"]]
                                .rename(columns={"estimate_pct": "Recorded scenario (%)"})
                            )
                            st.caption(
                                "The history begins when dated snapshots are recorded. "
                                "No earlier forecast values are invented."
                            )

                except Exception as exc:
                    st.error(
                        f"Forecast workspace could not be calculated: {type(exc).__name__}: {exc}"
                    )

            st.markdown("#### Sentiment and community observations")

            if selected_observations.empty:
                st.info(
                    "No observations are currently loaded for this district. "
                    "This is a data gap, not evidence of neutral sentiment."
                )
            else:
                # Clearly labelled filters; the underlying source records remain unchanged.
                f1, f2, f3 = st.columns(3)
                with f1:
                    issue_options = ["All issues"] + sorted(
                        selected_observations["issue"].dropna().unique().tolist()
                    )
                    issue_filter = st.selectbox("Issue", issue_options)
                with f2:
                    evidence_options = ["All evidence types"] + sorted(
                        selected_observations["evidence_class"].dropna().unique().tolist()
                    )
                    evidence_filter = st.selectbox("Evidence type", evidence_options)
                with f3:
                    confidence_options = ["All confidence levels"] + sorted(
                        selected_observations["confidence"].dropna().unique().tolist()
                    )
                    confidence_filter = st.selectbox("Source confidence", confidence_options)

                filtered = selected_observations.copy()
                if issue_filter != "All issues":
                    filtered = filtered[filtered["issue"] == issue_filter]
                if evidence_filter != "All evidence types":
                    filtered = filtered[filtered["evidence_class"] == evidence_filter]
                if confidence_filter != "All confidence levels":
                    filtered = filtered[filtered["confidence"] == confidence_filter]

                m1, m2, m3 = st.columns(3)
                m1.metric("Observations after filters", len(filtered))
                m2.metric("Distinct issues", filtered["issue"].nunique())
                m3.metric(
                    "Direct resident feedback",
                    int(filtered["evidence_class"].eq("direct_resident_feedback").sum()),
                )

                st.caption(
                    "These are documented observations, not a representative survey or "
                    "a measure of electorate-wide voting intention. Confidence refers to "
                    "the strength of the evidence record, not the strength of a party."
                )

                if not filtered.empty:
                    # Show published response distributions as individual consultation results.
                    # We do not average across unrelated proposals or treat these as polling.
                    response_columns = [
                        "support_pct", "oppose_pct", "conditional_support_pct",
                        "unsure_pct", "response_count", "survey_count",
                        "written_submissions", "engagement_count", "page_views"
                    ]
                    available_response_columns = [
                        column for column in response_columns if column in filtered.columns
                    ]
                    if available_response_columns:
                        has_reported_figures = filtered[available_response_columns].notna().any(axis=1)
                        response_rows = filtered.loc[has_reported_figures].copy()
                        if not response_rows.empty:
                            st.markdown("#### Published consultation response figures")
                            response_display = response_rows[
                                ["observation_date", "issue", "geographic_scope"] +
                                available_response_columns + ["source_url"]
                            ].rename(columns={
                                "observation_date": "Consultation period",
                                "issue": "Issue / proposal",
                                "geographic_scope": "Geographic scope",
                                "support_pct": "Support (%)",
                                "oppose_pct": "Oppose / not supportive (%)",
                                "conditional_support_pct": "Support with conditions (%)",
                                "unsure_pct": "Unsure (%)",
                                "response_count": "Recorded responses",
                                "survey_count": "Survey participants",
                                "written_submissions": "Written submissions",
                                "engagement_count": "Recorded contributions",
                                "page_views": "Consultation page views",
                                "source_url": "Source link",
                            })
                            st.dataframe(
                                response_display,
                                use_container_width=True,
                                hide_index=True,
                                column_config={
                                    "Source link": st.column_config.LinkColumn(
                                        "Source link", display_text="Open source ↗"
                                    )
                                },
                            )
                            st.caption(
                                "Figures are reported separately for each consultation. "
                                "They are not pooled or averaged: each consultation had its own "
                                "question, eligibility rules and self-selected participants."
                            )

                    display = filtered[
                        [
                            "observation_date", "issue", "sentiment_label",
                            "evidence_class", "confidence", "geographic_scope",
                            "source_name", "source_url"
                        ]
                    ].rename(
                        columns={
                            "observation_date": "Date",
                            "issue": "Issue",
                            "sentiment_label": "Observed classification",
                            "evidence_class": "Evidence type",
                            "confidence": "Evidence confidence",
                            "geographic_scope": "Geographic scope",
                            "source_name": "Source",
                            "source_url": "Source link",
                        }
                    )
                    st.dataframe(
                        display,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Source link": st.column_config.LinkColumn(
                                "Source link", display_text="Open source ↗"
                            )
                        },
                    )

                    st.markdown("#### Observation details")
                    for _, item in filtered.iterrows():
                        title = (
                            f"{item['observation_date']} · {item['issue']} · "
                            f"{item['sentiment_label'].replace('_', ' ')}"
                        )
                        with st.expander(title):
                            st.write(item["observation"])
                            st.caption(
                                f"Evidence: {item['evidence_class'].replace('_', ' ')} · "
                                f"Confidence: {item['confidence']}"
                            )
                            metric_items = [
                                ("Support", "support_pct", "%"),
                                ("Oppose / not supportive", "oppose_pct", "%"),
                                ("Support with conditions", "conditional_support_pct", "%"),
                                ("Unsure", "unsure_pct", "%"),
                                ("Recorded responses", "response_count", ""),
                                ("Survey participants", "survey_count", ""),
                                ("Written submissions", "written_submissions", ""),
                                ("Recorded contributions", "engagement_count", ""),
                                ("Consultation page views", "page_views", ""),
                            ]
                            visible_metrics = [
                                (label, item[column], suffix)
                                for label, column, suffix in metric_items
                                if column in item.index and pd.notna(item[column])
                            ]
                            if visible_metrics:
                                metric_columns = st.columns(min(4, len(visible_metrics)))
                                for index, (label, value, suffix) in enumerate(visible_metrics):
                                    metric_columns[index % len(metric_columns)].metric(
                                        label,
                                        f"{value:g}{suffix}" if suffix else f"{int(value):,}"
                                    )
                            st.write("**Geographic scope:** " + item["geographic_scope"])
                            st.write("**What this represents:** " + item["representativeness"])
                            st.write("**Target:** " + item.get("sentiment_target", "Not specified"))
                            if item["source_url"]:
                                st.markdown(f"[Open original source ↗]({item['source_url']})")
                else:
                    st.info("No observations match these filters.")

                st.markdown("#### Evidence over time")
                chart_data = filtered.dropna(subset=["date_sort"]).copy()
                if not chart_data.empty:
                    chart_data["Month"] = chart_data["date_sort"].dt.to_period("M").astype(str)
                    monthly = (
                        chart_data.groupby(["Month", "issue"])
                        .size()
                        .unstack(fill_value=0)
                        .sort_index()
                    )
                    st.bar_chart(monthly)
                    st.caption(
                        "Counts of collected source observations by publication month and issue. "
                        "This is not a sentiment score or a measure of prevalence among voters."
                    )

                st.markdown("#### Issues represented in the evidence")
                if not filtered.empty:
                    issue_counts = (
                        filtered.groupby("issue")
                        .size()
                        .sort_values(ascending=False)
                        .rename("Observation count")
                    )
                    st.bar_chart(issue_counts)

            st.markdown("#### Local news monitoring")
            st.caption(
                "News items are discovery leads, not measures of voter opinion. "
                "The collector stores article metadata and short snippets only; every item "
                "requires geographic and editorial review before analysis."
            )

            # Collect on demand so a page refresh does not repeatedly query external services.
            collect_col, source_col = st.columns([1, 2])
            with collect_col:
                if st.button("Collect latest local news", key="collect_kew_news", use_container_width=True):
                    with st.spinner("Checking local news sources and RSS searches..."):
                        try:
                            collection_result = collect_news(NEWS_PATH)
                            st.session_state["last_news_collection"] = collection_result
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"News collection failed: {type(exc).__name__}: {exc}")
            with source_col:
                st.caption(
                    "Sources: Boroondara newsroom, Google News RSS searches, "
                    "Eastsider News discovery and Victoria's Big Build."
                )

            if "last_news_collection" in st.session_state:
                result = st.session_state["last_news_collection"]
                st.success(
                    f"Collection complete: {result['new_items']} new items; "
                    f"{result['total_items']} stored; "
                    f"{result['feeds_succeeded']}/{result['feeds_attempted']} feeds succeeded."
                )
                if result["errors"]:
                    with st.expander("Collection warnings"):
                        for error in result["errors"]:
                            st.write("- " + error)

            news_df = NEWS_ARTICLES.copy()
            if not news_df.empty:
                st.markdown("#### Candidate coverage and public evidence")
                st.caption(
                    "Coverage counts describe how often a candidate appears in reviewed local "
                    "news items. They are not measures of popularity, support or voting intention. "
                    "Source-attributed public views are displayed individually, not combined into a score."
                )
                candidate_list = (
                    KEW_CANDIDATES["candidate_name"].tolist()
                    if not KEW_CANDIDATES.empty else []
                )
                if candidate_list:
                    candidate_focus = st.selectbox(
                        "Candidate to inspect",
                        candidate_list,
                        key="candidate_evidence_focus",
                    )
                    reviewed_candidate_news = news_df[
                        (news_df["review_status"] == "Reviewed")
                        & (news_df["geography_review"] == "Kew-specific")
                        & (news_df["candidate_mentions_reviewed"].fillna("") != "")
                    ].copy()
                    candidate_rows = reviewed_candidate_news[
                        reviewed_candidate_news["candidate_mentions_reviewed"].apply(
                            lambda value: candidate_focus in [
                                item.strip() for item in str(value).split(" | ") if item.strip()
                            ]
                        )
                    ].copy()

                    # Show source coverage volume over time, without direction or vote inference.
                    if not candidate_rows.empty:
                        candidate_rows["month"] = (
                            candidate_rows["published_sort"].dt.to_period("M").astype(str)
                        )
                        coverage_series = candidate_rows.groupby("month").size().rename(
                            "Reviewed local news items"
                        )
                        st.markdown(f"**{candidate_focus} — reviewed Kew-specific coverage**")
                        st.line_chart(coverage_series)
                        st.caption(
                            "A rise in coverage means more reviewed articles were collected, "
                            "not that support or opposition increased."
                        )

                        public_view_types = [
                            "Public endorsement of candidate",
                            "Public criticism of candidate",
                            "Public comment about candidate",
                        ]
                        public_view_rows = candidate_rows[
                            candidate_rows["candidate_evidence_type"].isin(public_view_types)
                        ].copy()
                        if not public_view_rows.empty:
                            public_view_rows["month"] = (
                                public_view_rows["published_sort"].dt.to_period("M").astype(str)
                            )
                            public_view_timeline = (
                                public_view_rows.groupby(
                                    ["month", "candidate_evidence_type"]
                                ).size().unstack(fill_value=0).sort_index()
                            )
                            st.markdown("**Source records of public views over time**")
                            st.bar_chart(public_view_timeline)
                            st.caption(
                                "Counts of reviewed articles containing attributed endorsements, "
                                "criticism or public comments. These are source-record counts, "
                                "not the number or proportion of voters holding those views."
                            )

                        st.markdown("**Source-attributed candidate evidence**")
                        for _, candidate_item in candidate_rows.iterrows():
                            with st.expander(
                                f"{candidate_item['published_at'][:10]} · "
                                f"{candidate_item['publisher']} · "
                                f"{candidate_item['candidate_evidence_type']}"
                            ):
                                st.write(candidate_item["title"])
                                st.write(candidate_item["candidate_public_view_summary"] or
                                         candidate_item["summary"])
                                st.caption(
                                    "Issue: " + str(candidate_item["issue_reviewed"] or
                                                    candidate_item["issue_suggested"])
                                )
                                st.markdown(
                                    f"[Open original source ↗]({candidate_item['source_url']})"
                                )
                    else:
                        st.info(
                            "No candidate-specific stories have yet been reviewed as Kew-specific "
                            "for this candidate. Review items below to build the time series."
                        )
                else:
                    st.info("Load the Kew candidate register to enable candidate-level review.")

            if news_df.empty:
                st.info(
                    "No news leads are stored yet. Select 'Collect latest local news' "
                    "to start a collection."
                )
            else:
                relevant_scope_options = ["All local leads"] + sorted(
                    news_df["geography_match"].dropna().unique().tolist()
                )
                nf1, nf2 = st.columns(2)
                with nf1:
                    geography_filter = st.selectbox(
                        "Geographic match", relevant_scope_options, key="news_geography_filter"
                    )
                with nf2:
                    review_filter = st.selectbox(
                        "Review status",
                        ["All", "Needs review", "Reviewed"],
                        key="news_review_filter",
                    )

                visible_news = news_df.copy()
                if geography_filter != "All local leads":
                    visible_news = visible_news[
                        visible_news["geography_match"] == geography_filter
                    ]
                if review_filter != "All":
                    visible_news = visible_news[
                        visible_news["review_status"] == review_filter
                    ]

                news_a, news_b, news_c = st.columns(3)
                news_a.metric("News leads stored", len(news_df))
                news_b.metric("Shown after filters", len(visible_news))
                news_c.metric(
                    "Awaiting review",
                    int(news_df["review_status"].eq("Needs review").sum()),
                )

                if not visible_news.empty:
                    news_table = visible_news[
                        [
                            "published_at", "title", "publisher",
                            "geography_match", "issue_suggested",
                            "review_status", "source_url"
                        ]
                    ].rename(columns={
                        "published_at": "Published",
                        "title": "Headline",
                        "publisher": "Publisher",
                        "geography_match": "Geographic match",
                        "issue_suggested": "Suggested issue",
                        "review_status": "Review status",
                        "source_url": "Article link",
                    })
                    st.dataframe(
                        news_table,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Article link": st.column_config.LinkColumn(
                                "Article link", display_text="Open article ↗"
                            )
                        },
                    )
                else:
                    st.info("No news leads match the selected filters.")

                st.markdown("##### Review a news item")
                review_ids = visible_news["article_id"].tolist()
                if review_ids:
                    review_id = st.selectbox(
                        "Choose an article",
                        review_ids,
                        format_func=lambda article_id: (
                            str(news_df.loc[news_df["article_id"] == article_id, "published_at"].iloc[0])[:10]
                            + " · "
                            + str(news_df.loc[news_df["article_id"] == article_id, "publisher"].iloc[0])
                            + " · "
                            + str(news_df.loc[news_df["article_id"] == article_id, "title"].iloc[0])[:85]
                        ),
                        key="news_review_article",
                    )
                    selected_article = news_df.loc[
                        news_df["article_id"] == review_id
                    ].iloc[0]

                    with st.expander("Read summary and review fields", expanded=True):
                        st.write(selected_article["summary"])
                        st.markdown(
                            f"[Open original article ↗]({selected_article['source_url']})"
                        )
                        st.caption(
                            "The automated issue label is only a suggestion. "
                            "Do not infer resident opinion from article tone."
                        )

                        with st.form("save_news_review"):
                            geo_choices = [
                                "Unreviewed", "Kew-specific", "Kew-area context",
                                "Boroondara-wide context", "Not relevant to Kew"
                            ]
                            geo_current = selected_article.get("geography_review", "Unreviewed")
                            geo_index = geo_choices.index(geo_current) if geo_current in geo_choices else 0
                            geography_review = st.selectbox(
                                "Geographic relevance", geo_choices, index=geo_index
                            )

                            issue_choices = [
                                "Unreviewed", "Planning and housing", "Transport and roads",
                                "Construction and disruption", "Environment and open space",
                                "Education", "Health and community services",
                                "Sport and recreation", "Council and local services",
                                "Crime and public safety", "Politics and election",
                                "Other / unclassified", "Not relevant"
                            ]
                            issue_current = selected_article.get("issue_reviewed", "") or "Unreviewed"
                            issue_index = issue_choices.index(issue_current) if issue_current in issue_choices else 0
                            issue_reviewed = st.selectbox(
                                "Issue classification", issue_choices, index=issue_index
                            )

                            tone_choices = [
                                "Not assessed", "Positive", "Negative", "Mixed",
                                "Neutral", "Factual / not applicable"
                            ]
                            tone_current = selected_article.get("article_tone", "Not assessed")
                            tone_index = tone_choices.index(tone_current) if tone_current in tone_choices else 0
                            article_tone = st.selectbox(
                                "Article framing / tone", tone_choices, index=tone_index
                            )

                            public_choices = [
                                "Not assessed", "No explicit public sentiment",
                                "Positive", "Negative", "Mixed", "Neutral / unclear"
                            ]
                            public_current = selected_article.get(
                                "public_sentiment_evidence", "Not assessed"
                            )
                            public_index = public_choices.index(public_current) if public_current in public_choices else 0
                            public_sentiment = st.selectbox(
                                "Public sentiment explicitly evidenced in article",
                                public_choices,
                                index=public_index,
                            )
                            sentiment_target = st.text_input(
                                "What is that sentiment about?",
                                value=str(selected_article.get("sentiment_target", "")),
                            )
                            st.markdown("**Candidate-specific evidence**")
                            candidate_options = (
                                KEW_CANDIDATES["candidate_name"].tolist()
                                if not KEW_CANDIDATES.empty else []
                            )
                            suggested_names = [
                                name for name in str(
                                    selected_article.get("candidate_mentions_suggested", "")
                                ).split(" | ") if name in candidate_options
                            ]
                            reviewed_names = [
                                name for name in str(
                                    selected_article.get("candidate_mentions_reviewed", "")
                                ).split(" | ") if name in candidate_options
                            ]
                            if not reviewed_names:
                                reviewed_names = suggested_names
                            candidate_mentions = st.multiselect(
                                "Candidates directly mentioned",
                                candidate_options,
                                default=reviewed_names,
                                help="Suggestions are based on exact name matches. Check the article before saving.",
                            )
                            candidate_evidence_choices = [
                                "Not assessed",
                                "Candidate statement / policy",
                                "Candidate campaign activity",
                                "Public endorsement of candidate",
                                "Public criticism of candidate",
                                "Public comment about candidate",
                                "Media profile / biographical coverage",
                                "No candidate-specific content",
                            ]
                            evidence_current = selected_article.get(
                                "candidate_evidence_type", "Not assessed"
                            )
                            evidence_index = (
                                candidate_evidence_choices.index(evidence_current)
                                if evidence_current in candidate_evidence_choices else 0
                            )
                            candidate_evidence_type = st.selectbox(
                                "Type of candidate-related evidence",
                                candidate_evidence_choices,
                                index=evidence_index,
                            )
                            candidate_public_view_summary = st.text_area(
                                "Source-attributed public view (summary, not a score)",
                                value=str(selected_article.get("candidate_public_view_summary", "")),
                                help="Record who expressed the view and what it concerned. Do not infer general voter opinion from one comment.",
                            )

                            review_notes = st.text_area(
                                "Review notes",
                                value=str(selected_article.get("review_notes", "")),
                            )
                            submitted = st.form_submit_button("Save article review")
                            if submitted:
                                row_index = news_df.index[
                                    news_df["article_id"] == review_id
                                ][0]
                                news_df.loc[row_index, "geography_review"] = geography_review
                                news_df.loc[row_index, "issue_reviewed"] = (
                                    "" if issue_reviewed == "Unreviewed" else issue_reviewed
                                )
                                news_df.loc[row_index, "article_tone"] = article_tone
                                news_df.loc[row_index, "public_sentiment_evidence"] = public_sentiment
                                news_df.loc[row_index, "sentiment_target"] = sentiment_target
                                news_df.loc[row_index, "candidate_mentions_reviewed"] = " | ".join(candidate_mentions)
                                news_df.loc[row_index, "candidate_evidence_type"] = candidate_evidence_type
                                news_df.loc[row_index, "candidate_public_view_summary"] = candidate_public_view_summary
                                news_df.loc[row_index, "review_notes"] = review_notes
                                news_df.loc[row_index, "review_status"] = "Reviewed"
                                news_df.drop(columns=["published_sort"], errors="ignore").to_csv(
                                    NEWS_PATH, index=False
                                )
                                st.cache_data.clear()
                                st.success("Review saved to data/news_articles.csv.")
                                st.rerun()

            st.markdown("#### Research status")
            st.write(
                "- Historical vote baseline: awaiting verified district result import\n"
                "- Search interest: not connected\n"
                "- Local news: RSS and newsroom collection enabled; manual review required\n"
                "- Public discussion: not connected\n"
                "- Model validation: not started"
            )

    else:
        st.metric("Legislative Council regions", "8")
        st.info(
            "Upper-house region and group-preference analysis is a separate module. "
            "Do not assume 2022 preference flows are directly comparable with the 2026 system."
        )
        st.write(
            "Regions: Eastern Victoria · North-Eastern Metropolitan · Northern Metropolitan · "
            "Northern Victoria · South-Eastern Metropolitan · Southern Metropolitan · "
            "Western Metropolitan · Western Victoria"
        )

    st.divider()
    st.markdown("#### 2022 statewide lower-house baseline")
    st.caption(
        "Historical VEC first-preference results. These are statewide results, "
        "not current voting intention."
    )
    baseline = pd.DataFrame(
        [
            {"Party": "Australian Labor Party", "First preference": 37.03},
            {"Party": "Liberal", "First preference": 29.60},
            {"Party": "Australian Greens", "First preference": 11.50},
            {"Party": "The Nationals", "First preference": 4.77},
            {"Party": "Family First Victoria", "First preference": 3.05},
            {"Party": "Animal Justice Party", "First preference": 2.51},
            {"Party": "Other parties and candidates", "First preference": 11.54},
        ]
    )
    st.bar_chart(baseline.set_index("Party"))
    st.caption(
        "Source: VEC 2022 State election results. Rounded/aggregated categories; "
        "consult the source for the full party breakdown."
    )
else:
    st.subheader(f"{jurisdiction} · Electoral register")
    st.info(
        "The database and ingestion interfaces are designed for all three jurisdictions. "
        "Federal and NSW electorate registers will be populated in a later data-loading step."
    )

st.divider()
st.markdown("#### Data integrity")
st.write(
    "This is a research instrument, not a polling service. Observed discussion, search "
    "interest, media tone and consultation feedback are not equivalent to voter preference. "
    "Any future statistical relationship will be labelled with its time period, sample "
    "coverage and validation performance."
)
st.caption(
    "Prototype version 0.6.3 · Built with Streamlit · No personal voter data is collected."
)
