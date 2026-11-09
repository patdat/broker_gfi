"""Validate the all-TD-route parquet against the xlsx + Josh masters."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import gfi_master


def _combined_source_rows():
    xlsx = gfi_master._load_td(gfi_master.XLSX_MASTER)
    josh = gfi_master._load_td(gfi_master.JOSH_MASTER)
    xlsx = gfi_master._drop_josh_covered(xlsx, josh)
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

    # TD3 is the XLSX alias for TD3C and must never become a second route column.
    assert 'TD3C' in routes
    assert 'TD3' not in routes
    assert 'TD25E' not in routes
    assert 'TD8' not in routes
    assert {'TD7', 'TD25', 'TD28'} <= set(routes)

    # Josh wins for the routes it quotes on the dates it covers, including
    # TD15, which the xlsx feed added on 2026-10-07 and Josh quotes since 09-14.
    josh = gfi_master._load_td(gfi_master.JOSH_MASTER)
    for route in ['TD7', 'TD15']:
        assert route in routes
        jrow = josh[(josh['instrument'] == route) & (josh['periodType'] == 'M')
                    & (josh['uom'] == 'WSC')].sort_values(['date', 'period']).iloc[-1]
        got = df[(df['date'] == jrow['date']) & (df['period'] == jrow['period'])
                 & (df['periodType'] == jrow['periodType']) & (df['uom'] == jrow['uom'])]
        assert len(got) == 1
        assert float(got.iloc[0][route]) == float(jrow['value'])


def test_xlsx_only_route_survives_a_josh_date():
    # Precedence is per (date, route): a route Josh does not quote keeps its
    # xlsx curve even on a date Josh covers, while a quoted route is replaced.
    cols = ['periodType', 'date', 'instrument', 'period', 'uom', 'value']
    day, contract = pd.Timestamp('2026-11-06'), pd.Timestamp('2027-01-01')
    xlsx = pd.DataFrame([['M', day, 'TD15', contract, 'PMT', 95.0],
                         ['M', day, 'TD7', contract, 'WSC', 120.0]], columns=cols)
    josh = pd.DataFrame([['M', day, 'TD7', contract, 'WSC', 121.0]], columns=cols)
    kept = gfi_master._drop_josh_covered(xlsx, josh)
    assert kept['instrument'].tolist() == ['TD15']


def test_build_gfi_master_writes_parquet(tmp_path, monkeypatch):
    out_path = tmp_path / 'gfi_master.parquet'
    monkeypatch.setattr(gfi_master, 'OUT_PATH', str(out_path))

    expected = gfi_master.build_gfi_master(upload=False)
    actual = pd.read_parquet(out_path)

    pd.testing.assert_frame_equal(actual, expected)


if __name__ == '__main__':
    test_build_frame()
    print('test_build_frame OK')
