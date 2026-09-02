"""Build the combined TD7/TD25 cash-arb parquet from the xlsx + josh masters.

`gfi_cash_arb.parquet` is a compact, pivoted view for downstream arb work: only
the `TD7` and `TD25` routes, with the `instrument` column pivoted into two value
columns (`TD7`, `TD25`) to shrink the file, and the `source` column dropped.

The two masters are combined with **josh taking precedence by report date**: for
any `date` present in the josh master, that date's rows come from josh and the
xlsx rows for the same date are dropped; xlsx supplies every date josh doesn't
cover. Josh currently starts 2026-08-10, so it wins the recent tail and xlsx
provides the longer history before it.

The pivot key is `['periodType', 'date', 'period', 'uom']` (verified collision-
free in both masters), so no values are aggregated away."""

import os

import pandas as pd

XLSX_MASTER = './data/GFI_xlsx.csv'
JOSH_MASTER = './data/GFI_josh.csv'
OUT_PATH = './data/gfi_cash_arb.parquet'
CLOUD_FOLDER = 'BROKER/MASTER'
CLOUD_NAME = 'gfi_cash_arb.parquet'

INSTRUMENTS = ['TD7', 'TD25']
INDEX_COLS = ['periodType', 'date', 'period', 'uom']
OUT_COLS = INDEX_COLS + INSTRUMENTS  # source dropped; instrument pivoted away

# periodTypes to exclude from the export. MTD (month-to-date) is xlsx-only — josh
# uses BAL (balance-of-month) instead — so it only ever appears on pre-josh dates
# and creates a boundary seam; drop it.
DROP_PERIODTYPES = ['MTD']


def _load_td(path):
    """Read a master and keep only the TD7/TD25 rows we pivot on."""
    df = pd.read_csv(path, parse_dates=['date', 'period'])
    return df[df['instrument'].isin(INSTRUMENTS)].copy()


def build_frame():
    """Combine xlsx + josh (josh wins by date) and pivot to the cash-arb shape."""
    xlsx = _load_td(XLSX_MASTER)
    josh = _load_td(JOSH_MASTER)

    # josh precedence by report date: drop xlsx rows for any date josh covers
    josh_dates = set(josh['date'].unique())
    xlsx = xlsx[~xlsx['date'].isin(josh_dates)]

    combined = pd.concat([xlsx, josh], ignore_index=True)
    combined = combined[~combined['periodType'].isin(DROP_PERIODTYPES)]

    pivoted = combined.pivot_table(
        index=INDEX_COLS, columns='instrument', values='value', aggfunc='first')
    # guarantee both columns exist even if one instrument is ever absent
    for col in INSTRUMENTS:
        if col not in pivoted.columns:
            pivoted[col] = pd.NA
    pivoted = pivoted.reset_index()
    pivoted.columns.name = None
    return pivoted[OUT_COLS].sort_values(['date', 'uom', 'periodType', 'period']).reset_index(drop=True)


def _upload(path):
    """Upload the parquet to S3; a cloud error must never break the pipeline."""
    try:
        from utils.cloud import upload_file
        return upload_file(path, CLOUD_FOLDER, os.path.basename(path))
    except Exception as e:
        print(f'Cloud upload skipped for {path}: {type(e).__name__}: {e}')
        return None


def build_cash_arb(upload=True):
    """Build gfi_cash_arb.parquet, write it locally, and (optionally) upload to S3.

    Returns the built DataFrame."""
    df = build_frame()
    df.to_parquet(OUT_PATH, index=False)
    print(f'CASH_ARB: wrote {OUT_PATH} ({len(df)} rows, dates '
          f'{df["date"].min().date()}..{df["date"].max().date()})')
    if upload:
        _upload(OUT_PATH)
    return df


if __name__ == '__main__':
    build_cash_arb()
