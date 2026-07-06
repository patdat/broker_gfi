import os
import pandas as pd
import datetime

def shorten_csv(df,dayCounter=30):
    df = df.copy()
    today = datetime.date.today()
    start = today - datetime.timedelta(days=dayCounter)
    start = pd.to_datetime(start)
    df = df[df['date'] >= start].copy()
    return df

def uploadToCloud(localPath, cloudFolder):
    """Upload one local file to S3; a cloud error must never break the local pipeline."""
    try:
        from utils.cloud import upload_file
        upload_file(localPath, cloudFolder, os.path.basename(localPath))
    except Exception as e:
        print(f'Cloud upload skipped for {localPath}: {type(e).__name__}: {e}')

def processBroker(df,inputFolder,masterName,masterFolder='./data/master/',cloudFolder='BROKER/MASTER'):
    df = df.copy()
    os.makedirs('./data/shortened', exist_ok=True)

    # files written locally then pushed to the cloud: master + latest date + trailing windows
    uploads = [f'./data/{masterName}.csv']  # master itself, written upstream in main.py

    # most recent date only
    latestPath = f'./data/shortened/{masterName}_last.csv'
    df[df['date'] == df['date'].max()].to_csv(latestPath, index=False)
    uploads.append(latestPath)

    daysList = [60,30]
    for i in daysList:
        df = shorten_csv(df,i)
        windowPath = f'./data/shortened/{masterName}_{i}.csv'
        df.to_csv(windowPath, index=False)
        uploads.append(windowPath)

    for path in uploads:
        uploadToCloud(path, cloudFolder)
