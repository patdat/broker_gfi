"""Build the combined, pivoted all-TD-route parquet.

`gfi_master.parquet` is the broad-route companion to `gfi_cash_arb.parquet`.
It uses the same xlsx/Josh merge policy and 2D shape, keeps instruments whose
names begin with ``TD`` except explicitly excluded routes, and pivots each
retained route into a value column.

Josh takes precedence per route and report date: when Josh quotes a route on
a date, every xlsx row for that route and date is discarded, so a single
route's daily curve never mixes the two broker layouts.  Routes Josh does not
quote on a date (e.g. ``TD15``, which only the xlsx feed carries) still come
from xlsx.
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
EXCLUDED_INSTRUMENTS = {'TD8', 'TD25E'}


def _load_td(path):
    """Read a long-format master and keep instruments beginning with TD."""
    df = pd.read_csv(path, parse_dates=['date', 'period'])
    is_td = df['instrument'].astype('string').str.upper().str.startswith('TD', na=False)
    df = df[is_td].copy()
    # TD3 is the XLSX feed's raw label for TD3C. Keep one canonical route name
    # even when this builder is pointed at a pre-normalization master.
    df['instrument'] = df['instrument'].replace({'TD3': 'TD3C'})
    df = df[~df['instrument'].isin(EXCLUDED_INSTRUMENTS)]
    return df


def _route_sort_key(route):
    """Sort route columns naturally (TD3C, TD7, ..., TD25E)."""
    match = re.fullmatch(r'([^0-9]*)([0-9]+)(.*)', str(route))
    if match is None:
        return (str(route), -1, '')
    return (match.group(1), int(match.group(2)), match.group(3))


def _drop_josh_covered(xlsx, josh):
    """Drop xlsx rows for each (date, route) that Josh also quotes.

    A route's daily curve comes wholly from one feed; xlsx-only routes survive.
    """
    josh_keys = josh[['date', 'instrument']].drop_duplicates()
    merged = xlsx.merge(josh_keys, on=['date', 'instrument'], how='left', indicator=True)
    keep = (merged['_merge'] == 'left_only').to_numpy()
    return xlsx[keep]


def build_frame():
    """Combine xlsx + Josh and pivot every TD route into a value column."""
    xlsx = _load_td(XLSX_MASTER)
    josh = _load_td(JOSH_MASTER)

    xlsx = _drop_josh_covered(xlsx, josh)
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
