"""Fetch the VEC's published 2022 district-results workbook and save a raw copy.

The workbook's internal sheet/column layout can change. This script deliberately
preserves the workbook and prints sheet/column names for an explicit mapping step.
"""
from pathlib import Path
import requests
import pandas as pd

ROOT = Path(__file__).parent
URL = 'https://vec.vic.gov.au/-/media/c4665365795d431e811d0ce818e373d4.xlsx'
RAW = ROOT / 'data/raw'
RAW.mkdir(parents=True, exist_ok=True)
DEST = RAW / 'vec_2022_all_district_results.xlsx'

r = requests.get(URL, timeout=60, headers={'User-Agent': 'ElectoralSentimentResearch/0.1'})
r.raise_for_status()
if not r.content[:2] == b'PK':
    raise RuntimeError('Downloaded content does not look like an XLSX workbook. Check the VEC source URL.')
DEST.write_bytes(r.content)
print(f'Saved {DEST} ({len(r.content):,} bytes)')
book = pd.ExcelFile(DEST)
print('Worksheets:', book.sheet_names)
for sheet in book.sheet_names:
    df = pd.read_excel(DEST, sheet_name=sheet, nrows=5)
    print(f'\n[{sheet}] columns: {list(df.columns)}')
    print(df.head(2).to_string(index=False))
print('\nNext: map the verified columns into the canonical election_results schema. Do not infer fields from column position.')
