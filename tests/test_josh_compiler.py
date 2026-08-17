import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())


def test_seed_and_schema():
    import main
    df = main.seedJoshMaster()
    assert list(df.columns) == ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']
    assert len(df) > 0
    # master round-trips from disk with the same row count
    on_disk = pd.read_csv('./data/GFI_josh.csv', parse_dates=['date', 'period'])
    assert len(on_disk) == len(df)
    # all 6 report dates present
    assert on_disk['date'].dt.strftime('%Y-%m-%d').nunique() == 6
    # no dupes on the 5-key
    key = ['periodType', 'date', 'instrument', 'period', 'uom']
    assert not on_disk.duplicated(subset=key).any()
    print(f'test_seed_and_schema OK ({len(df)} rows)')


if __name__ == '__main__':
    test_seed_and_schema()
