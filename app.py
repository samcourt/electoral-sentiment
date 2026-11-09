import streamlit as st
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DISTRICTS_PATH = DATA_DIR / "vic_districts_2026.csv"
OBSERVATIONS_PATH = DATA_DIR / "kew_seed_observations.csv"
RESULTS_PATH = DATA_DIR / "vic_2022_district_results.csv"

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
    return observations.sort_values(["date_sort", "issue"], ascending=[False, True])

DISTRICTS, HAS_DISTRICT_REGISTER = load_districts()
OBSERVATIONS = load_observations()

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

            st.markdown("#### Research status")
            st.write(
                "- Historical vote baseline: awaiting verified district result import\n"
                "- Search interest: not connected\n"
                "- Local news feed: manual seed observations only\n"
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
    "Prototype version 0.2 · Built with Streamlit · No personal voter data is collected."
)
