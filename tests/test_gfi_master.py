"""Validate the all-TD-route parquet against the xlsx + Josh masters."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import gfi_master


def _combined_source_rows():
    xlsx = gfi_master._load_td(gfi_master.XLSX_MASTER)
    josh = gfi_master._load_td(gfi_master.JOSH_MASTER)
    xlsx = xlsx[~xlsx['date'].isin(set(josh['date'].unique()))]
    combined = pd.concat([xlsx, josh], ignore_index=True)
    return combined[~combined['periodType'].isin(gfi_master.DROP_PERIODTYPES)]


def test_build_frame():
    df = gfi_master.build_frame()
    combined = _combined_source_rows()
    routes = sorted(combined['instrument'].dropna().unique(), key=gfi_master._route_sort_key)

    assert list(df.columns) == gfi_master.INDEX_COLS + routes
    assert all(route.startswith('TD') for route in routes)
    assert 'source' not in df.columns
    assert 'instrument' not in df.columns
    assert (df['periodType'] != 'MTD').all()

    # Every retained long-form quote becomes exactly one non-null route cell.
    assert not combined.duplicated(gfi_master.INDEX_COLS + ['instrument']).any()
    assert int(df[routes].notna().sum().sum()) == len(combined)
    assert len(df) == len(combined.drop_duplicates(gfi_master.INDEX_COLS))

    # The widest current feeds are represented, including source-specific routes.
    assert {'TD3', 'TD3C', 'TD7', 'TD25', 'TD25E', 'TD28'} <= set(routes)

    # Josh wins on dates it covers.
    josh = gfi_master._load_td(gfi_master.JOSH_MASTER)
    jrow = josh[(josh['instrument'] == 'TD7') & (josh['periodType'] == 'M')
                & (josh['uom'] == 'WSC')].sort_values(['date', 'period']).iloc[-1]
    got = df[(df['date'] == jrow['date']) & (df['period'] == jrow['period'])
             & (df['periodType'] == jrow['periodType']) & (df['uom'] == jrow['uom'])]
    assert len(got) == 1
    assert float(got.iloc[0]['TD7']) == float(jrow['value'])


def test_build_gfi_master_writes_parquet(tmp_path, monkeypatch):
    out_path = tmp_path / 'gfi_master.parquet'
    monkeypatch.setattr(gfi_master, 'OUT_PATH', str(out_path))

    expected = gfi_master.build_gfi_master(upload=False)
    actual = pd.read_parquet(out_path)

    pd.testing.assert_frame_equal(actual, expected)


if __name__ == '__main__':
    test_build_frame()
    print('test_build_frame OK')
