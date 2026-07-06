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


def csvCompiler(counter):
    since = get_cursor('GFI_csvs')
    newFiles, latest = downloader_csv(counter, since)
    if latest is not None:
        set_cursor('GFI_csvs', latest)  # advance pointer over everything we accounted for

    newFiles = sorted(newFiles)
    if not newFiles:
        print('CSV: no new reports - skipping parse and upload')
        return None
    print(f'CSV: {len(newFiles)} new file(s): {newFiles}')

    df = pd.DataFrame()
    for file in newFiles:
        df = pd.concat([df, read_csv_file(file)])

    masterFile = pd.read_csv('./data/GFI_csvs.csv', parse_dates=['date','period'])
    rowsBefore = len(masterFile)
    df = pd.concat([masterFile, df])
    df = df.drop_duplicates(subset=['periodType', 'date', 'instrument', 'period'], keep='last')
    if len(df) <= rowsBefore:
        print('CSV: new files added no new rows - skipping upload')
        return None

    df.to_csv('./data/GFI_csvs.csv', index=False)
    processBroker(df, './data/', 'GFI_csvs', './data/master/', 'BROKER/MASTER')
    return df


def xlsxDownloader(counter):
    since = get_cursor('GFI_xlsx')
    newFiles, latest = downloader_xlsx(counter, since)
    if latest is not None:
        set_cursor('GFI_xlsx', latest)  # advance pointer over everything we accounted for

    newFiles = sorted(newFiles)
    if not newFiles:
        print('XLSX: no new reports - skipping parse and upload')
        return None
    print(f'XLSX: {len(newFiles)} new file(s): {newFiles}')

    df = pd.DataFrame()
    for file in newFiles:
        df = pd.concat([df, read_xlsx_file(file)])

    masterFile = pd.read_csv('./data/GFI_xlsx.csv', parse_dates=['date','period'])
    rowsBefore = len(masterFile)
    df = pd.concat([masterFile, df])
    df = df.drop_duplicates(subset=['periodType', 'date', 'instrument', 'period'], keep='last')
    if len(df) <= rowsBefore:
        print('XLSX: new files added no new rows - skipping upload')
        return None

    df.to_csv('./data/GFI_xlsx.csv', index=False)
    processBroker(df, './data/', 'GFI_xlsx', './data/master/', 'BROKER/MASTER')
    copyToKDrive(['./data/GFI_xlsx.csv', './data/shortened/GFI_xlsx_last.csv'])
    return df


def main(counter):
    print(f'Run condition (today > latest date in master): {runFunctionCheck}')
    if runFunctionCheck == True:
        csvCompiler(counter)
        xlsxDownloader(counter)
    else:
        print('Master already up to date for today - nothing to do.')


if __name__ == '__main__':
    import datetime
    from utils.logger import setup_logging
    logpath = setup_logging()
    print(f'=== broker_gfi run started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} | log: {logpath} ===')
    try:
        main(5)
        print('=== run completed successfully ===')
    except Exception:
        import traceback
        print('=== run FAILED ===')
        traceback.print_exc()
        raise
