import os
import sys
import glob
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_josh_file

PERIODTYPES = {'M', 'Q', 'A', 'BAL', 'BITR', 'WSFR'}
UOMS = {'WSC', 'PMT', 'LSM', 'WSFR'}
KEEP = {'TD3C', 'TD20', 'TD7', 'TD8', 'TD19', 'TD22', 'TD25', 'TD28',
        'USG Afra Exc', 'USG Afra Inc'}
SCHEMA = ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']


def test_all_files():
    files = sorted(os.path.basename(p) for p in glob.glob('data/josh/*.xlsx'))
    # at least the 6 original fixtures; the scheduler accretes more over time
    assert len(files) >= 6, f'expected >=6 fixtures, found {files}'
    for f in files:
        df = read_josh_file.main(f)
        assert list(df.columns) == SCHEMA, f'{f}: bad schema {list(df.columns)}'
        assert len(df) > 0, f'{f}: no rows'
        assert set(df.periodType) <= PERIODTYPES, f'{f}: bad periodTypes {set(df.periodType)}'
        assert set(df.uom) <= UOMS, f'{f}: bad uoms {set(df.uom)}'
        assert set(df.instrument) <= KEEP, f'{f}: unexpected instruments {set(df.instrument) - KEEP}'
        assert df.value.notna().all(), f'{f}: null values present'
        # date column equals the file's date name
        assert (df.date == pd.Timestamp(f[:-5])).all(), f'{f}: date mismatch'
        print(f'{f}: {len(df)} rows OK')
    print('test_all_files OK')


if __name__ == '__main__':
    test_all_files()
