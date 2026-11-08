import os
import sys
import shutil
from pathlib import Path
import pandas as pd

sys.path.insert(0, os.getcwd())


def test_seed_and_schema(tmp_path, monkeypatch):
    import main
    root = Path.cwd()
    shutil.copytree(root / 'data/josh', tmp_path / 'data/josh')
    shutil.copytree(root / 'lookup', tmp_path / 'lookup')
    monkeypatch.chdir(tmp_path)
    df = main.seedJoshMaster()
    assert list(df.columns) == ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']
    assert len(df) > 0
    # master round-trips from disk with the same row count
    on_disk = pd.read_csv('./data/GFI_josh.csv', parse_dates=['date', 'period'])
    assert len(on_disk) == len(df)
    # at least the 6 original report dates present (scheduler accretes more)
    assert on_disk['date'].dt.strftime('%Y-%m-%d').nunique() >= 6
    # no dupes on the 5-key
    key = ['periodType', 'date', 'instrument', 'period', 'uom']
    assert not on_disk.duplicated(subset=key).any()
    print(f'test_seed_and_schema OK ({len(df)} rows)')
