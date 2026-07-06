import pandas as pd
global lookupPeriod
lookupPeriod = pd.read_csv('./lookup/periods.csv')

def replacePeriods(df,lookupPeriod):
    df = df.copy()    
    df = pd.merge(df, lookupPeriod, on='period', how='left')
    beginningOfMonth = df['reportDate'] - pd.offsets.MonthBegin(1)
    df['plmName'] = df['plmName'].fillna(beginningOfMonth)
    df['plmName'] = pd.to_datetime(df['plmName'])
    return df
    
def finalTouches(df):
    df = df.copy()
    #drop period column
    df = df.drop(columns=['period'])
    df['source'] = 'GFI'
    df.rename(columns={'periodicity':'periodType'}, inplace=True)
    df.rename(columns={'reportDate':'date'}, inplace=True)
    df.rename(columns={'route':'instrument'}, inplace=True)
    df.rename(columns={'value':'price'}, inplace=True)
    df.rename(columns={'plmName':'period'}, inplace=True)
    df = df[['source','periodType','date','instrument','period','price']]
    return df

def csv_reading(filename):
    fileDate = filename.split('.')[0]
    fileDate = pd.to_datetime(fileDate)
    df = pd.read_csv(f'./data/csv/{filename}', header=None)
    df.iloc[0,0] = 'description'
    df.iloc[1,0] = 'route'
    df = df.T
    df.columns = df.iloc[0]
    df = df[1:]
    df = df.dropna(subset=['description'])
    df = df.dropna(axis=1, how='all')
    df = df.drop(columns=['description'])
    df
    df = df.melt(id_vars=['route'], var_name='period', value_name='value')
    df['route'] = df['route'].str.upper()
    df['period'] = df['period'].str.upper()
    df = df[df['period']!='BITR CHANGE']
    df = df[df['period']!='MTD CHANGE']
    df = df[df['route'].str.contains('TD', na=False)]  # na=False drops blank/trailing rows
    df['reportDate'] = fileDate
    df = replacePeriods(df,lookupPeriod)
    df = finalTouches(df)
    return df

def main(file):
    df = csv_reading(file)
    return df

if __name__ == '__main__':
    df = main('2024-03-14.csv') 