import pandas as pd
import os
import shutil

from utils.downloader_csv import main as downloader_csv
from utils.read_csv_file import main as read_csv_file

from utils.downloader_xlsx import main as downloader_xlsx
from utils.read_xlsx_file import main as read_xlsx_file
from utils.shorten_csv import processBroker
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


def xlsxDownloader(counter, force=False):
    since = None if force else get_cursor('GFI_xlsx')
    newFiles, latest = downloader_xlsx(counter, since)
    if latest is not None:
        set_cursor('GFI_xlsx', latest)  # advance pointer over everything we accounted for

    newFiles = sorted(newFiles)
    masterFile = pd.read_csv('./data/GFI_xlsx.csv', parse_dates=['date','period'])

    if newFiles:
        print(f'XLSX: {len(newFiles)} new file(s): {newFiles}')
        df = pd.DataFrame()
        for file in newFiles:
            df = pd.concat([df, read_xlsx_file(file)])
        rowsBefore = len(masterFile)
        df = pd.concat([masterFile, df])
        df = df.drop_duplicates(subset=['periodType', 'date', 'instrument', 'period'], keep='last')
        newRows = len(df) > rowsBefore
    else:
        print('XLSX: no new reports')
        df = masterFile
        newRows = False

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


def main(counter, force=False):
    print(f'Run condition (today > latest date in master): {runFunctionCheck}{" [FORCED]" if force else ""}')
    if force or runFunctionCheck == True:
        csvCompiler(counter, force)
        xlsxDownloader(counter, force)
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
