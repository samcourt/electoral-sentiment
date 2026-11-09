# Australian Electoral Sentiment Tracker — prototype 0.5.1

A neutral public-data research prototype. Initial live case: Victoria's 2026 state election. The architecture is designed to expand to federal and NSW elections.

## What's included

- Streamlit dashboard with a searchable register of Victoria's 88 current Legislative Assembly districts.
- Complete 88-district Victorian Legislative Assembly register in `data/vic_districts_2026.csv`.
- Kew pilot evidence ledger loaded from `data/kew_seed_observations.csv`, with filters for issue, evidence type and confidence, source links, observation detail, monthly evidence counts and separately reported consultation response figures. The app opens on Kew by default.
- Local news discovery pipeline in `news_monitor.py`, using eight Google News RSS searches plus direct Boroondara newsroom and Victoria's Big Build work-notice indexes.
- Five manually sourced Kew news leads in `data/news_articles.csv` to seed the review queue.
- Official 2026 Kew candidate register in `data/kew_2026_candidates.csv` (10 candidates, VEC ballot order).
- Official 2022 Kew first-preference and final preference-distribution baseline in `data/kew_2022_results.csv`.
- One published March 2026 Kew uComms poll record in `data/kew_polls.csv`, including sample size, commissioning disclosure, a 36%/38% reported discrepancy for Jess Wilson and missing-methodology caveats.
- Dated Victorian statewide polling ledger in `data/vic_state_polls_2026.csv`, including eligibility flags and quality weights.
- Kew first-preference scenario model in `kew_forecast.py`, with a conditional Coalition–Labor uniform-swing scenario.
- Separately-labelled external Kew forecast and final-two benchmarks in `data/kew_external_forecast_benchmarks.csv` and `data/kew_external_2cp_benchmarks.csv`.
- Dated model snapshots in `data/kew_forecast_snapshots.csv`.
- Candidate-specific Google News discovery queries and an editorial review form that links news items to candidates and source-attributed public views.
- Candidate coverage time series based only on reviewed, Kew-specific news items; coverage volume is not a popularity or voting-intention measure.
- News source register in `data/news_sources.csv`, including coverage and limitations.
- Structured consultation fields include support/opposition percentages, conditional support, unsure responses, response counts, survey counts, written submissions, recorded contributions and page views. Blank fields mean not published/not available; they are not zero.
- Victoria's eight Legislative Council regions as a separate view.
- Official 2022 statewide first-preference baseline (historical context only).
- Canonical PostgreSQL schema for jurisdictions, election cycles, electorates, election results, observations, sentiment classifications and weekly indicators.
- VEC workbook ingestion helper that downloads and inspects the official 2022 district-results workbook without guessing its internal schema.
- Source register and data-quality notes.

**Important:** there is no continuous automated sentiment feed, district-level 2022 result import, or boundary geometry yet. Local news collection is on-demand and requires human review. The Kew observations are a manually curated seed dataset; some are reports of constituent concerns or consultation summaries rather than direct, representative resident measurements. Consultation response percentages are shown separately by proposal and are never pooled or averaged. The app does not create synthetic sentiment scores. Forecast outputs are explicitly labelled exploratory scenarios, not calibrated predictions.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Kew polling trends, scenarios and forecast history (prototype 0.5)

The Kew profile includes an exploratory polling and scenario workspace. It is intentionally transparent about what is measured, assumed and not known.

### Statewide poll ledger

`data/vic_state_polls_2026.csv` stores dated statewide primary-vote polls, fieldwork dates, sample sizes, reported Coalition two-party-preferred figures where available, inclusion status and source links. The dashboard shows every stored poll as a time-series observation, including excluded or superseded records for context.

The default in-project average uses the latest eligible poll from each pollster and applies a 14-day exponential recency half-life multiplied by the `quality_weight` stored in the poll ledger. These quality weights are provisional project judgements, not an official rating. Internal/party-commissioned polls and superseded results are retained but excluded from the default average. The dashboard compares our average with an external published average; it does not blend the two.

### Kew first-preference scenario

`kew_forecast.py` starts with the March 2026 uComms Kew poll. Jess Wilson and Sophie Torney were named in the reported options; Labor and One Nation were party-intention options (the One Nation candidate had not yet been selected), not personal candidate measures. The model then adjusts the relevant party candidates by the change between the March Resolve Victorian component poll and the current weighted statewide poll average. The Greens candidate is anchored to the 2022 Kew Greens result and adjusted by statewide Greens polling change. Other candidates use historical Kew results or clearly-labelled statewide proxies where necessary.

This is a deliberately simple scenario rule, not a fitted predictive model. The uComms poll was commissioned by Sophie Torney's campaign, is several months old, has incomplete reported candidate options, and has a published discrepancy for Jess Wilson (38% in The Poll Bludger versus 36% in a news.com.au report). That discrepancy is preserved in `data/kew_polls.csv`. Candidates without a defensible baseline remain unestimated; the residual vote is shown as **Unallocated / unmodelled vote** rather than being silently assigned to them.

The pass-through slider allows the user to test how much statewide polling movement is assumed to transfer to Kew. Candidate vote checkpoints compare 2022 actual results, the March local poll and the current scenario, while flagging candidate/party proxies. Its 0.5×–1.5× sensitivity range is not a statistical confidence interval.

### Conditional Coalition–Labor scenario

The uniform-swing scenario applies the current statewide Coalition two-party-preferred share change to the 2022 Kew final Liberal–Labor preference distribution. It is conditional on Jess Wilson and David Sun being the final two candidates. It does not estimate which candidates will finish first and second, and it should not be called the likely final 2CP when an independent or One Nation candidate could finish ahead of Labor.

`data/kew_external_forecast_benchmarks.csv` and `data/kew_external_2cp_benchmarks.csv` hold a separately-labelled AEF Kew forecast benchmark dated 30 October 2026. Those values are not produced by this project. They provide a comparison point and should be rechecked for date/freshness before interpretation.

### Forecast history

Use **Record today's Kew forecast snapshot** to append a dated model snapshot to `data/kew_forecast_snapshots.csv`. The dashboard then charts saved snapshots over time. The app writes this file in the Codespace working tree; commit it to GitHub periodically to retain the forecast history.

### Current model limitations

- There is only one known seat-level Kew poll in the data, commissioned by a candidate campaign, and it is old and incompletely reported.
- Statewide polling is not a direct measurement of Kew candidate support.
- The model does not yet estimate preference transfers for Wilson–Torney, Wilson–Laird or other possible final pairs.
- The model has not been backtested on previous elections and does not produce its own win probabilities.
- News coverage and source-attributed public views are not used as vote-share inputs until they have a sufficiently large, reviewed and historically validated dataset.

## Candidate research — Kew

`data/kew_2026_candidates.csv` contains the ten candidates in the official VEC ballot order. Candidate-specific Google News RSS searches are added to the local news collector. Exact-name matches are suggestions only and must be checked against the article.

`data/kew_2022_results.csv` stores the official 2022 first-preference result for each candidate and the final preference distribution. In 2022, the final distribution was between Jess Wilson (Liberal) and Lucy Skelton (Labor): 53.98% to 46.02%. The early booth-level 2CP count was not the same as the final electorate-wide preference distribution. This historical record is not a current estimate.

In the Kew news review form, select the candidates directly mentioned, classify the type of candidate-related evidence, and summarise any public view with attribution. The candidate panel charts the volume of reviewed Kew-specific news items over time, charts counts of source records by public-view evidence type, and lists the underlying evidence. It does not calculate candidate sentiment scores, projected first-preference shares, 2PP/2CP forecasts or a projected winner. Coverage and evidence-record volume are not popularity, support or voting intention. Published polls and final electoral results may be displayed separately with their source, date, geography, sample and measurement type.

A March 2026 uComms poll of 914 Kew respondents, commissioned by Sophie Torney's campaign and reported in the press, is stored in `data/kew_polls.csv`. The source review did not establish exact field dates, sampling mode, weighting, question wording or margin of error. It is displayed as a dated, campaign-commissioned poll measurement, not as an independent consensus or current estimate.

## Local news monitoring — Kew pilot

The Kew profile has an on-demand **Collect latest local news** button. It runs `news_monitor.py`, which checks:

- Eight Google News RSS searches for Kew, Kew East, Boroondara, local planning/services, Eastsider News and Big Build stories.
- The City of Boroondara newsroom index.
- Victoria's Big Build North East Link work-notices index, retaining links that specifically mention Kew or Kew East.

The collector is discovery infrastructure, not a sentiment engine. It stores article metadata, publisher, publication date, source URL and a short RSS/index snippet. It does not download full articles. Keyword issue labels and geographic matches are suggestions only.

Every article starts as **Needs review**. In the Kew profile, use **Review a news item** to record:
- Whether it is Kew-specific, nearby-area context, Boroondara-wide context or irrelevant.
- The issue classification.
- Article framing/tone (kept separate from what residents say).
- Whether the article contains explicit public sentiment evidence, and what it is about.

Do not infer resident sentiment from a journalist's tone, government project update or political statement. An article mentioning Kew is not automatically relevant to the Kew electorate. Review the geography and evidence before using it in any analysis.

### News files

- `data/news_articles.csv`: current news leads and reviewer annotations.
- `data/news_sources.csv`: monitored sources and known limitations.
- `data/news_collection_log.csv`: created locally by each collection run, with successful/failed feed counts.

Collection and review update `data/news_articles.csv` in the Codespace working tree. Commit the updated CSV to GitHub periodically if you want the collected history backed up in the repository and available in a fresh Codespace.

The collector is on-demand; it does not run in the background. Keep refreshes sensible and respect publisher terms and access controls. Article links always point to the original publisher or its RSS discovery link.

The ABC RSS service is not included because the ABC states that its RSS feeds are no longer being updated. Eastsider News is included as an indexed discovery query; it publishes periodic local editions rather than a verified live RSS feed.

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
| Kew seed observations | Source-linked council consultations, planning engagement, parliamentary reports and issue signals | Kew, with explicitly labelled broader-area proxies | Loaded into the Kew profile; current file contains 12 records. Consultation responses are self-selected and not representative polling |
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
