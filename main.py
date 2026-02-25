import pandas as pd
import os

from utils.downloader_csv import main as downloader_csv
from utils.read_csv_file import main as read_csv_file

from utils.downloader_xlsx import main as downloader_xlsx
from utils.read_xlsx_file import main as read_xlsx_file
from utils.shorten_csv import processBroker


def checkRunCondition():
    df = pd.read_csv('./data/GFI_csvs.csv',parse_dates=['date','period'])
    maxDate = df['date'].max()
    today = pd.to_datetime('today').normalize()

    runFunctionCheck = today > maxDate
    return runFunctionCheck
runFunctionCheck = checkRunCondition()

def csvCompiler(counter):
    downloader_csv(counter)

    files = os.listdir('./data/csv')
    files.sort()
    files = files[-counter:]
    

    df = pd.DataFrame()
    for file in files:
        data = read_csv_file(file)
        df = pd.concat([df, data])
        
    masterFile = pd.read_csv('./data/GFI_csvs.csv',parse_dates=['date','period'])
    df = pd.concat([masterFile,df])
    df = df.drop_duplicates(subset=['periodType', 'date', 'instrument', 'period'], keep='last') 
    df.to_csv('./data/GFI_csvs.csv', index=False)
    processBroker(df,'./data/', 'GFI_csvs', './data/master/', 'BROKER/MASTER')


    return df    

def xlsxDownloader(counter):
    downloader_xlsx(counter)

    files = os.listdir('./data/xlsx')
    files.sort()
    files = files[-counter:]

    df = pd.DataFrame()
    for file in files:
        data = read_xlsx_file(file)
        df = pd.concat([df, data])
        
    masterFile = pd.read_csv('./data/GFI_xlsx.csv',parse_dates=['date','period'])
    df = pd.concat([masterFile,df])
    df = df.drop_duplicates(subset=['periodType', 'date', 'instrument', 'period'], keep='last') 
    df.to_csv('./data/GFI_xlsx.csv', index=False)
    processBroker(df,'./data/', 'GFI_xlsx', './data/master/', 'BROKER/MASTER')

    return df
    
def main(counter):
    if runFunctionCheck == True:
        csvCompiler(counter)
        xlsxDownloader(counter)    

if __name__ == '__main__':
    main(5)