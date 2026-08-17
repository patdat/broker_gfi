"""One-shot: rename data/josh/Curves*.xlsx to <internal-date>.xlsx.

The internal date is the file's own cell iloc[0,0] (the report date), the same
value the production downloader names files by. Idempotent: files already named
YYYY-MM-DD.xlsx are skipped."""

import os
import glob
import re
import warnings
import pandas as pd

JOSH_DIR = './data/josh'
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def main():
    for path in sorted(glob.glob(os.path.join(JOSH_DIR, '*.xlsx'))):
        base = os.path.splitext(os.path.basename(path))[0]
        if _DATE_RE.match(base):
            print(f'skip (already dated): {base}.xlsx')
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            df = pd.read_excel(path, header=None)
        datestr = pd.to_datetime(df.iloc[0, 0]).strftime('%Y-%m-%d')
        assert _DATE_RE.match(datestr), f'bad date {datestr!r} from {path}'
        dest = os.path.join(JOSH_DIR, f'{datestr}.xlsx')
        os.rename(path, dest)
        print(f'renamed: {os.path.basename(path)} -> {datestr}.xlsx')


if __name__ == '__main__':
    main()
