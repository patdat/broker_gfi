import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_josh_file

FILE = '2026-08-17.xlsx'


def _val(df, instrument, periodType, uom, period):
    m = df[(df.instrument == instrument) & (df.periodType == periodType)
           & (df.uom == uom) & (df.period == pd.Timestamp(period))]
    assert len(m) == 1, f'expected 1 row, got {len(m)} for {instrument}/{periodType}/{uom}/{period}'
    return float(m.iloc[0].value)


def test_wsfr_and_bitr():
    df = read_josh_file.main(FILE)

    # WSFR: one row per instrument, period = first of report month
    assert _val(df, 'TD3C', 'WSFR', 'WSFR', '2026-08-01') == 20.21
    assert _val(df, 'USG Afra Exc', 'WSFR', 'WSFR', '2026-08-01') == 21.01
    # TD22 has no WSFR value -> no row
    assert df[(df.instrument == 'TD22') & (df.periodType == 'WSFR')].empty

    # BITR from the Linked table, period = first of report month
    assert _val(df, 'TD3C', 'BITR', 'WSC', '2026-08-01') == 501.67
    assert _val(df, 'TD25', 'BITR', 'WSC', '2026-08-01') == 377.22
    # TD22 BITR is in raw millions in the Linked table -> /1e6, uom LSM
    assert abs(_val(df, 'TD22', 'BITR', 'LSM', '2026-08-01') - 18.791667) < 1e-6

    # TD28 and USG Afra are not in the Linked table -> no BITR rows
    assert df[(df.instrument == 'TD28') & (df.periodType == 'BITR')].empty
    assert df[(df.instrument.str.contains('USG')) & (df.periodType == 'BITR')].empty

    print('test_wsfr_and_bitr OK')


if __name__ == '__main__':
    test_wsfr_and_bitr()
