import pandas as pd
import numpy as np
import os
import shutil

from utils.downloader_csv import main as downloader_csv
from utils.read_csv_file import main as read_csv_file

from utils.downloader_xlsx import main as downloader_xlsx
from utils.read_xlsx_file import main as read_xlsx_file
from utils.downloader_josh import main as downloader_josh
from utils.read_josh_file import main as read_josh_file
from utils.shorten_csv import processBroker
from utils.cash_arb import build_cash_arb
from utils.gfi_master import build_gfi_master
from utils.state import get_cursor, set_cursor

K_DRIVE_DEST = r'K:\plm_prices'


def copyToKDrive(paths):
    if not os.path.isdir(K_DRIVE_DEST):
        print(f'{K_DRIVE_DEST} not available on this machine - skipping K: copy')
        return
    for src in paths:
        try:
            shutil.copy2(src, os.path.join(K_DRIVE_DEST, os.path.basename(src)))
            print(f'Copied {src} -> {K_DRIVE_DEST}')
        except Exception as e:
            print(f'K:\\ copy skipped for {src}: {type(e).__name__}: {e}')


def checkRunCondition():
    df = pd.read_csv('./data/GFI_csvs.csv',parse_dates=['date','period'])
    maxDate = df['date'].max()
    today = pd.to_datetime('today').normalize()

    runFunctionCheck = today > maxDate
    return runFunctionCheck
runFunctionCheck = checkRunCondition()


def csvCompiler(counter, force=False):
    since = None if force else get_cursor('GFI_csvs')
    newFiles, latest = downloader_csv(counter, since)
    if latest is not None:
        set_cursor('GFI_csvs', latest)  # advance pointer over everything we accounted for

    newFiles = sorted(newFiles)
    masterFile = pd.read_csv('./data/GFI_csvs.csv', parse_dates=['date','period'])

    if newFiles:
        print(f'CSV: {len(newFiles)} new file(s): {newFiles}')
        df = pd.DataFrame()
        for file in newFiles:
            df = pd.concat([df, read_csv_file(file)])
        rowsBefore = len(masterFile)
        df = pd.concat([masterFile, df])
        df = df.drop_duplicates(subset=['periodType', 'date', 'instrument', 'period'], keep='last')
        newRows = len(df) > rowsBefore
    else:
        print('CSV: no new reports')
        df = masterFile
        newRows = False

    if not newRows and not force:
        print('CSV: nothing new - skipping upload')
        return None

    if newRows:
        df.to_csv('./data/GFI_csvs.csv', index=False)
    else:
        print('CSV: [FORCED] no new rows - re-publishing existing master')
    processBroker(df, './data/', 'GFI_csvs', './data/master/', 'BROKER/MASTER')
    return df


def mtdFromCsvMaster():
    """The Braemar xlsx feed has no MTD (month-to-date) field - only the GFI csv
    feed does. Pull the MTD rows out of the csv master and reshape them to the
    xlsx schema so GFI_xlsx.csv carries them too. Read fresh from disk each run
    (csvCompiler runs first, so the csv master is already current)."""
    cols = ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']
    csvMaster = pd.read_csv('./data/GFI_csvs.csv', parse_dates=['date', 'period'])
    mtd = csvMaster[csvMaster['periodType'] == 'MTD'].copy()
    if mtd.empty:
        return pd.DataFrame(columns=cols)

    mtd['instrument'] = mtd['instrument'].replace({'TD3C': 'TD3'})  # xlsx names this route TD3
    mtd = mtd.rename(columns={'price': 'value'})
    # LSM for TD22 (÷1e6, matching the xlsx feed's LSM convention), WSC for the rest
    mtd['uom'] = np.where(mtd['instrument'] == 'TD22', 'LSM', 'WSC')
    mtd['value'] = np.where(mtd['instrument'] == 'TD22', mtd['value'] / 1_000_000, mtd['value'])
    mtd['source'] = 'GFI'
    return mtd[cols]


def xlsxDownloader(counter, force=False):
    since = None if force else get_cursor('GFI_xlsx')
    newFiles, latest = downloader_xlsx(counter, since)
    if latest is not None:
        set_cursor('GFI_xlsx', latest)  # advance pointer over everything we accounted for

    newFiles = sorted(newFiles)
    masterFile = pd.read_csv('./data/GFI_xlsx.csv', parse_dates=['date','period'])
    rowsBefore = len(masterFile)

    parts = [masterFile]
    if newFiles:
        print(f'XLSX: {len(newFiles)} new file(s): {newFiles}')
        for file in newFiles:
            parts.append(read_xlsx_file(file))
    else:
        print('XLSX: no new reports')
    parts.append(mtdFromCsvMaster())  # MTD carried over from the csv feed (xlsx has none)

    df = pd.concat(parts)
    df = df.drop_duplicates(subset=['periodType', 'date', 'instrument', 'period'], keep='last')
    newRows = len(df) > rowsBefore

    if not newRows and not force:
        print('XLSX: nothing new - skipping upload')
        return None

    if newRows:
        df.to_csv('./data/GFI_xlsx.csv', index=False)
    else:
        print('XLSX: [FORCED] no new rows - re-publishing existing master')
    processBroker(df, './data/', 'GFI_xlsx', './data/master/', 'BROKER/MASTER')
    copyToKDrive(['./data/GFI_xlsx.csv', './data/shortened/GFI_xlsx_last.csv'])
    return df


def seedJoshMaster():
    """Build data/GFI_josh.csv from every file currently in ./data/josh.

    One-time bootstrap: parses all fixtures, dedupes, writes the master. Safe to
    re-run (idempotent — dedupe on the 5-key keeps the last row)."""
    files = sorted(f for f in os.listdir('./data/josh') if f.endswith('.xlsx'))
    parts = [read_josh_file(f) for f in files]
    df = pd.concat(parts) if parts else pd.DataFrame(
        columns=['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value'])
    df = df.drop_duplicates(
        subset=['periodType', 'date', 'instrument', 'period', 'uom'], keep='last')
    df.to_csv('./data/GFI_josh.csv', index=False)
    print(f'JOSH: seeded master from {len(files)} file(s): {len(df)} rows')
    return df


def joshDownloader(counter, force=False):
    since = None if force else get_cursor('GFI_josh')
    newFiles, latest = downloader_josh(counter, since)
    if latest is not None:
        set_cursor('GFI_josh', latest)

    newFiles = sorted(newFiles)
    masterFile = pd.read_csv('./data/GFI_josh.csv', parse_dates=['date', 'period'])
    rowsBefore = len(masterFile)

    parts = [masterFile]
    if newFiles:
        print(f'JOSH: {len(newFiles)} new file(s): {newFiles}')
        for file in newFiles:
            parts.append(read_josh_file(file))
    else:
        print('JOSH: no new reports')

    df = pd.concat(parts)
    df = df.drop_duplicates(
        subset=['periodType', 'date', 'instrument', 'period', 'uom'], keep='last')
    newRows = len(df) > rowsBefore

    if not newRows and not force:
        print('JOSH: nothing new - skipping upload')
        return None

    if newRows:
        df.to_csv('./data/GFI_josh.csv', index=False)
    else:
        print('JOSH: [FORCED] no new rows - re-publishing existing master')
    processBroker(df, './data/', 'GFI_josh', './data/master/', 'BROKER/MASTER')
    copyToKDrive(['./data/GFI_josh.csv', './data/shortened/GFI_josh_last.csv'])
    return df


def main(counter, force=False):
    print(f'Run condition (today > latest date in master): {runFunctionCheck}{" [FORCED]" if force else ""}')
    if force or runFunctionCheck == True:
        csvCompiler(counter, force)
        xlsxDownloader(counter, force)
        joshDownloader(counter, force)
        # combined TD7/TD25 cash-arb parquet (josh wins by date); reads the
        # masters fresh, so it reflects whatever the three pipelines just wrote
        build_cash_arb()
        # Same 2D layout for every instrument beginning with TD.
        build_gfi_master()
    else:
        print('Master already up to date for today - nothing to do. (use --force to override)')


if __name__ == '__main__':
    import argparse
    import datetime
    from utils.logger import setup_logging

    parser = argparse.ArgumentParser(description='GFI / Braemar broker ETL')
    parser.add_argument('--force', action='store_true',
                        help='ignore data/state.json (the cursor) and the once-per-day run gate; re-scan the full --days window')
    parser.add_argument('--days', type=int, default=5,
                        help='look-back window in days when there is no cursor / on --force (default: 5)')
    cli = parser.parse_args()

    logpath = setup_logging()
    banner = f'=== broker_gfi run started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} | log: {logpath}'
    if cli.force:
        banner += ' | FORCE'
    print(banner + ' ===')
    try:
        main(cli.days, force=cli.force)
        print('=== run completed successfully ===')
    except Exception:
        import traceback
        print('=== run FAILED ===')
        traceback.print_exc()
        raise
