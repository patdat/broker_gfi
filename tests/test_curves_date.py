import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import report_date

def test_read_curves_date():
    ts = report_date.read_curves_date('data/josh/2026-08-17.xlsx')
    assert ts == pd.Timestamp('2026-08-17'), ts
    print('test_read_curves_date OK')

if __name__ == '__main__':
    test_read_curves_date()
