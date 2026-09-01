"""The josh parser takes the magnitude of values: a broker sign-flip bad print
(negative month-end Balmo) must come through positive, and no negative value
should ever appear in the parsed output.

Uses the real 2026-08-27 file, whose source WS-block Balmo prints TD25 -290.25
and TD28 -0.250001."""

import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_josh_file

FILE = '2026-08-27.xlsx'


def test_negatives_become_positive():
    df = read_josh_file.main(FILE)

    # no negative survives anywhere
    assert (df['value'] >= 0).all(), df[df['value'] < 0].to_string(index=False)

    # the specific bad prints come through as their magnitude
    def val(inst, uom):
        m = df[(df.instrument == inst) & (df.periodType == 'BAL') & (df.uom == uom)
               & (df.period == pd.Timestamp('2026-08-01'))]
        assert len(m) == 1, f'{inst}/{uom}: expected 1 row, got {len(m)}'
        return float(m.iloc[0].value)

    assert val('TD25', 'WSC') == 290.25   # source -290.25
    assert val('TD25', 'PMT') == 62.32    # source -62.32
    assert val('TD28', 'LSM') == 0.25     # source -0.250001
    assert val('TD28', 'PMT') == 3.13     # source -3.13

    print('test_negatives_become_positive OK')


if __name__ == '__main__':
    test_negatives_become_positive()
