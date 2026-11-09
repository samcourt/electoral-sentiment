import streamlit as st
import pandas as pd
from pathlib import Path
import json

ROOT = Path(__file__).parent
DISTRICTS = pd.read_csv(ROOT / 'data/vic_districts_2026.csv')
RESULTS_PATH = ROOT / 'data/vic_2022_district_results.csv'

st.set_page_config(page_title='Electoral Sentiment Tracker', page_icon='📊', layout='wide')
st.title('Australian Electoral Sentiment Tracker')
st.caption('Research prototype · Victoria 2026 live case · Federal and NSW schemas included')

with st.sidebar:
    st.header('Explore')
    jurisdiction = st.selectbox('Jurisdiction', ['Victoria', 'Federal', 'NSW'])
    if jurisdiction == 'Victoria':
        level = st.radio('Chamber', ['Legislative Assembly', 'Legislative Council'], horizontal=False)
        if level == 'Legislative Assembly':
            district = st.selectbox('Electorate', ['All districts'] + DISTRICTS['district'].tolist())
        else:
            district = st.selectbox('Region', ['All regions', 'Eastern Victoria', 'North-Eastern Metropolitan', 'Northern Metropolitan', 'Northern Victoria', 'South-Eastern Metropolitan', 'Southern Metropolitan', 'Western Metropolitan', 'Western Victoria'])
    else:
        st.info('The federal and NSW geographic registers are included in the project schema. Their electorate datasets are the next ingestion step.')
        district = 'All electorates'
    metric = st.selectbox('Research view', ['Election baseline', 'Issue sentiment', 'Political discussion', 'Search interest', 'News coverage', 'Economic context', 'Data quality'])

if jurisdiction == 'Victoria':
    st.subheader('Victoria · 2026 State Election')
    st.write('Election day: **28 November 2026** · 88 Legislative Assembly districts · 8 Legislative Council regions')
    if level == 'Legislative Assembly':
        a,b,c,d = st.columns(4)
        a.metric('Districts', '88')
        b.metric('Last state election', '2022')
        c.metric('Current campaign', '2026')
        d.metric('Sentiment observations', '0', help='No live sentiment feeds have been connected yet.')
        st.info('This prototype deliberately does not invent district-level sentiment or voting-intention estimates. It provides the district register, historical baseline context and ingestion workflow.')
        if district == 'All districts':
            st.markdown('#### District register')
            st.dataframe(DISTRICTS, use_container_width=True, hide_index=True)
        else:
            row = DISTRICTS.loc[DISTRICTS.district == district].iloc[0]
            st.markdown(f'### {district}')
            st.write(f"2026 district profile: [Victorian Electoral Commission]({row.vec_url})")
            if RESULTS_PATH.exists():
                results = pd.read_csv(RESULTS_PATH)
                subset = results[results.astype(str).apply(lambda col: col.str.contains(district, case=False, na=False)).any(axis=1)]
                if not subset.empty:
                    st.dataframe(subset, use_container_width=True, hide_index=True)
                else:
                    st.warning('The historical district results file has been loaded, but this district could not be matched automatically. Inspect the source field mapping before using it.')
            else:
                st.warning('District-level 2022 results have not yet been imported. Use the ingestion instructions in README.md.')
            st.markdown('#### Sentiment observations')
            st.caption('No observations collected. Connect source feeds before interpreting this district.')
            st.markdown('#### Research status')
            st.write('- Historical vote baseline: awaiting district result import\n- Search interest: not connected\n- Local news: not connected\n- Public discussion: not connected\n- Model validation: not started')
    else:
        st.metric('Legislative Council regions', '8')
        st.info('Upper-house region and group-preference analysis is a separate module. The 2026 voting-system changes mean 2022 preference flows should not be treated as directly comparable.')
        st.write('Regions: Eastern Victoria · North-Eastern Metropolitan · Northern Metropolitan · Northern Victoria · South-Eastern Metropolitan · Southern Metropolitan · Western Metropolitan · Western Victoria')

    st.divider()
    st.markdown('#### 2022 statewide lower-house baseline')
    st.caption('Official VEC first-preference results. These are statewide historical results, not current voting intention.')
    baseline = pd.DataFrame([
        {'Party': 'Australian Labor Party', 'First preference': 37.03},
        {'Party': 'Liberal', 'First preference': 29.60},
        {'Party': 'Australian Greens', 'First preference': 11.50},
        {'Party': 'The Nationals', 'First preference': 4.77},
        {'Party': 'Family First Victoria', 'First preference': 3.05},
        {'Party': 'Animal Justice Party', 'First preference': 2.51},
        {'Party': 'Other parties and candidates', 'First preference': 11.54},
    ])
    st.bar_chart(baseline.set_index('Party'))
    st.caption('Source: VEC 2022 State election results. Rounded/aggregated categories; consult the source for full party breakdown.')
else:
    st.subheader(f'{jurisdiction} · Electoral register')
    st.info('The database and ingestion interfaces are designed for all three jurisdictions. Federal and NSW electorate registers will be populated in the next data-loading step.')

st.divider()
st.markdown('#### Data integrity')
st.write('This is a research instrument, not a polling service. Observed discussion, search interest and media tone are not equivalent to voter preference. Any future statistical relationship will be labelled with its time period, sample coverage and validation performance.')
st.caption('Prototype version 0.1 · Built with Streamlit · No personal voter data is collected.')
