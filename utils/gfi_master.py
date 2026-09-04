"""Build the combined, pivoted all-TD-route parquet.

`gfi_master.parquet` is the full-route companion to `gfi_cash_arb.parquet`.
It uses the same xlsx/Josh merge policy and 2D shape, but keeps every
instrument whose name begins with ``TD`` and pivots each route into a value
column.

Josh takes precedence by report date: when Josh covers a date, all xlsx rows
for that date are discarded.  This prevents the two broker layouts from being
mixed within a single daily curve.
"""

import os
import re

import pandas as pd


XLSX_MASTER = './data/GFI_xlsx.csv'
JOSH_MASTER = './data/GFI_josh.csv'
OUT_PATH = './data/gfi_master.parquet'
CLOUD_FOLDER = 'BROKER/MASTER'
CLOUD_NAME = 'gfi_master.parquet'

INDEX_COLS = ['periodType', 'date', 'period', 'uom']
DROP_PERIODTYPES = ['MTD']


def _load_td(path):
    """Read a long-format master and keep instruments beginning with TD."""
    df = pd.read_csv(path, parse_dates=['date', 'period'])
    is_td = df['instrument'].astype('string').str.upper().str.startswith('TD', na=False)
    return df[is_td].copy()


def _route_sort_key(route):
    """Sort route columns naturally (TD3, TD3C, TD7, ..., TD25E)."""
    match = re.fullmatch(r'([^0-9]*)([0-9]+)(.*)', str(route))
    if match is None:
        return (str(route), -1, '')
    return (match.group(1), int(match.group(2)), match.group(3))


def build_frame():
    """Combine xlsx + Josh and pivot every TD route into a value column."""
    xlsx = _load_td(XLSX_MASTER)
    josh = _load_td(JOSH_MASTER)

    # Josh precedence by report date: a daily curve comes wholly from one feed.
    josh_dates = set(josh['date'].unique())
    xlsx = xlsx[~xlsx['date'].isin(josh_dates)]

    combined = pd.concat([xlsx, josh], ignore_index=True)
    combined = combined[~combined['periodType'].isin(DROP_PERIODTYPES)]
    routes = sorted(combined['instrument'].dropna().unique(), key=_route_sort_key)

    # Use pivot (rather than an aggregating pivot_table) so an unexpected key
    # collision fails loudly instead of silently discarding a quote.
    pivoted = combined.pivot(
        index=INDEX_COLS, columns='instrument', values='value').reset_index()
    pivoted.columns.name = None
    out_cols = INDEX_COLS + routes
    return pivoted[out_cols].sort_values(
        ['date', 'uom', 'periodType', 'period']).reset_index(drop=True)


def _upload(path):
    """Upload the parquet to S3; a cloud error must never break the pipeline."""
    try:
        from utils.cloud import upload_file
        return upload_file(path, CLOUD_FOLDER, os.path.basename(path))
    except Exception as e:
        print(f'Cloud upload skipped for {path}: {type(e).__name__}: {e}')
        return None


def build_gfi_master(upload=True):
    """Build, write, and optionally upload ``gfi_master.parquet``."""
    df = build_frame()
    df.to_parquet(OUT_PATH, index=False)
    print(f'GFI_MASTER: wrote {OUT_PATH} ({len(df)} rows, '
          f'{len(df.columns) - len(INDEX_COLS)} routes, dates '
          f'{df["date"].min().date()}..{df["date"].max().date()})')
    if upload:
        _upload(OUT_PATH)
    return df


if __name__ == '__main__':
    build_gfi_master()
