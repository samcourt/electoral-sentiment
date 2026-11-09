# Australian Electoral Sentiment Tracker — prototype 0.1

A neutral public-data research prototype. Initial live case: Victoria's 2026 state election. The architecture is designed to expand to federal and NSW elections.

## What's included

- Streamlit dashboard with a searchable register of Victoria's 88 current Legislative Assembly districts.
- Victoria's eight Legislative Council regions as a separate view.
- Official 2022 statewide first-preference baseline (historical context only).
- Canonical PostgreSQL schema for jurisdictions, election cycles, electorates, election results, observations, sentiment classifications and weekly indicators.
- VEC workbook ingestion helper that downloads and inspects the official 2022 district-results workbook without guessing its internal schema.
- Source register and data-quality notes.

**Important:** no live sentiment feed, district-level 2022 result import, or boundary geometry is included yet. The app explicitly labels those gaps. It does not create synthetic scores or infer voting intention.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Import the official VEC 2022 district workbook

```bash
python ingest_vec_2022.py
```

The script preserves the downloaded workbook and prints sheet and column names. Inspect those names before mapping to the canonical schema. The VEC results page links the workbook as its spreadsheet of all 2022 district results. The direct download URL is embedded in the script; if the VEC changes it, update the URL from the official results page.

Official results page: https://vec.vic.gov.au/results/state-election-results/2022-state-election-results

## Geographic boundaries

Use the current VEC district/region boundaries for the relevant election cycle. The Victorian Government's Vicmap Admin dataset describes the 2022 lower-house and upper-house electoral boundary layers. Do not treat the 2022 boundary vintage as automatically equivalent to a later redistribution. Store a boundary version against every electorate and election cycle.

- VEC district register: https://vec.vic.gov.au/electoral-boundaries/state-districts
- VEC boundary downloads: https://vec.vic.gov.au/electoral-boundaries/download-boundary-maps
- Vicmap Admin: https://discover.data.vic.gov.au/dataset/vicmap-admin

## Research principles

1. Separate raw observations from derived classifications and model outputs.
2. Keep source URL, publication time, retrieval time, geography and licence/terms with every observation.
3. Never equate search volume, news tone or online discussion with voter preference.
4. Report geographic resolution honestly. State-level Google Trends cannot be presented as electorate-level data.
5. Track source coverage and missingness; don't silently impute missing districts.
6. Validate sentiment classifiers against manually reviewed samples.
7. Backtest only with data that would have been available at the historical prediction date.
8. Compare against simple baselines and publish uncertainty and limitations.
9. Do not profile individual voters or infer their political preferences.

## Initial source register

| Source | Use | Geography | Status |
|---|---|---|---|
| VEC 2022 results | Historical district first preferences and preference counts | District / voting centre | Workbook download helper included |
| VEC 2026 election page | Election date, candidates and official notices | District / region | Manual source |
| VEC district register | Current district names and profile links | District | 88 districts loaded |
| VEC 2026 candidate spreadsheet | Candidate names and affiliations | District / region | Source registered; import pending |
| VEC 2026 results feed | Live first-preference and 2CP count data | District / region | Access approval and terms agreement required |
| Vicmap Admin | Boundary geometries | District / region | Download and validate separately |
| AEC results | Federal historical results | Division / polling place / SA1 | Planned |
| NSWEC results | NSW historical results | District / polling place | Planned |
| ABS | Demographic and socioeconomic context | SA1 / LGA | Planned |
| Google Trends | Search-interest time series | Mostly state / region | Planned; access and resolution limitations |
| News RSS / public articles | Issue and entity coverage | Article-level; geocoding required | Planned; terms and reuse checks required |
| Public online discussion | Aggregate topic/sentiment measures | Usually coarse or unknown | Planned; platform terms and representativeness checks required |

## Suggested next engineering steps

1. Run the VEC workbook helper and map the verified worksheet fields into `election_results`.
2. Download the authoritative district and region geometries and create a PostGIS layer.
3. Add 2018 and 2014 VEC results for historical backtesting, recording boundary changes.
4. Add federal and NSW election registers and historical results.
5. Add a weekly observations collector, starting with a permitted Google Trends workflow and a small set of RSS feeds.
6. Add human-reviewed sentiment labels and classifier evaluation before producing aggregate sentiment indicators.
