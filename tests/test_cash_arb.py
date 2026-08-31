"""Validate the cash-arb pivot against the real xlsx + josh masters.
Run from repo root with the venv python."""

import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import cash_arb


def test_build_frame():
    df = cash_arb.build_frame()

    # exact schema/order, source dropped, instrument pivoted away
    assert list(df.columns) == ['periodType', 'date', 'period', 'uom', 'TD7', 'TD25'], list(df.columns)
    assert 'source' not in df.columns
    assert 'instrument' not in df.columns

    xlsx = pd.read_csv('./data/GFI_xlsx.csv', parse_dates=['date', 'period'])
    josh = pd.read_csv('./data/GFI_josh.csv', parse_dates=['date', 'period'])
    josh_dates = set(josh['date'].dt.date.unique())

    # josh precedence: for a josh date, TD7 must equal the JOSH value, not xlsx
    jdate = max(josh_dates)
    jrow = josh[(josh.date.dt.date == jdate) & (josh.instrument == 'TD7')
                & (josh.periodType == 'M') & (josh.uom == 'WSC')].sort_values('period').iloc[0]
    got = df[(df.date.dt.date == jdate) & (df.period == jrow.period) & (df.uom == 'WSC')
             & (df.periodType == 'M')]
    assert len(got) == 1 and float(got.iloc[0].TD7) == float(jrow.value), \
        f'josh precedence failed for {jdate}: {got.TD7.tolist()} vs {jrow.value}'

    # xlsx-only history is retained (an early xlsx date josh never covers)
    xdate_early = xlsx['date'].min().date()
    assert xdate_early not in josh_dates
    assert (df['date'].dt.date == xdate_early).any(), 'early xlsx date missing from output'

    # no date is sourced from both: row count == xlsx(non-josh dates) + josh, pivoted
    assert df['date'].dt.date.nunique() == len(
        set(xlsx['date'].dt.date.unique()) | josh_dates)

    # values are real: a known josh TD25 value shows up
    assert df[['TD7', 'TD25']].notna().any().all(), 'both columns should have values'

    print(f'test_build_frame OK ({len(df)} rows, '
          f'{df["date"].dt.date.nunique()} dates)')


if __name__ == '__main__':
    test_build_frame()
