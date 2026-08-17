"""Curve-block assertions for read_josh_file, against data/josh/2026-08-17.xlsx.
Run from repo root with the venv python."""

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


def test_curve_values():
    df = read_josh_file.main(FILE)

    # schema + source/date
    assert list(df.columns) == ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']
    assert (df['source'] == 'GFI').all()
    assert (df['date'] == pd.Timestamp('2026-08-17')).all()

    # WSC front-month + Balmo + PMT (values rounded to 2 decimals in the parser)
    assert _val(df, 'TD3C', 'M', 'WSC', '2026-08-01') == 470
    assert _val(df, 'TD3C', 'BAL', 'WSC', '2026-08-01') == 470.19  # 470.18555... -> 470.19
    assert _val(df, 'TD3C', 'M', 'PMT', '2026-08-01') == 94.99  # 94.987 -> 94.99

    # LSM routes in the WS block (no division)
    assert _val(df, 'TD22', 'M', 'LSM', '2026-08-01') == 19.5
    assert _val(df, 'TD28', 'BAL', 'LSM', '2026-08-01') == 2.64  # 2.63703... -> 2.64

    # quarter + cal tenor resolution
    assert _val(df, 'TD3C', 'Q', 'WSC', '2026-10-01') == 440
    assert _val(df, 'TD3C', 'A', 'WSC', '2027-01-01') == 275.85  # 275.85353... -> 275.85

    # USG Afra kept, verbatim-ish names
    assert _val(df, 'USG Afra Exc', 'M', 'WSC', '2026-08-01') == 345.46
    assert _val(df, 'USG Afra Inc', 'M', 'WSC', '2026-08-01') == 360

    # dropped: TC*, BLPG*, X-UK Cont P.
    assert df[df.instrument.str.startswith('TC')].empty
    assert df[df.instrument.str.startswith('BLPG')].empty
    assert df[df.instrument.str.contains('UK')].empty

    # strip dropped: TD3C WSC has exactly BAL(1)+months(8)+quarters(7)+cals(3)+BITR(1)=20 rows
    assert len(df[(df.instrument == 'TD3C') & (df.uom == 'WSC')]) == 20

    print('test_curve_values OK')


if __name__ == '__main__':
    test_curve_values()
