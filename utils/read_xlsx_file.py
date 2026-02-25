import pandas as pd
import os
import numpy as np
import warnings
warnings.simplefilter("ignore")

files = os.listdir('./data/xlsx')
lookup = pd.read_csv('./lookup/periods.csv')

def readFile(file):
    df = pd.read_excel('./data/xlsx/' + file,header=None)
    date_string = df.iloc[2,0]
    date_obj = pd.to_datetime(date_string)
    date_obj_bom = date_obj.replace(day=1)

    columns = df.iloc[4].astype(str) + "_" + df.iloc[5].astype(str)
    df.columns = columns

    df = df.drop([0,1,2,3,4,5])
    df = df.iloc[:,1:]

    df = df.rename(columns={'Route_nan':'route'})
    df.columns = df.columns.str.replace('\n', '')

    df = df.melt(id_vars=['route'],var_name='period',value_name='value')
    df['period'] = np.where(df['period'] == 'nan_BITR','BITR_WS',df['period'])

    df[['period','uom']] = df['period'].str.split('_',expand=True)
    df['uom'] = df['uom'].str.upper()

    df['route'] = df['route'].str.upper()
    df = df[df['route'].str.contains('TD')]

    df['value'] = np.where((df['route'] == 'TD22') & (df['period'] == 'BITR'),df['value']/1000000,df['value'])
    df['uom'] = np.where((df['route'] == 'TD22'),'LSM',df['uom'])

    df['uom'] = np.where(df['uom'] == 'WS','WSC',df['uom'])
    df['uom'] = np.where(df['uom'] == '$/TONNE','PMT',df['uom'])

    df['value'] = pd.to_numeric(df['value'],errors='coerce')
    df = df.dropna(subset=['value'])

    df['period'] = df['period'].str.upper()

    df = pd.merge(df,lookup,how='left',on='period')
    df['plmName'] = np.where(df['period'] == 'BITR',date_obj_bom,df['plmName'])

    df['plmName'] = pd.to_datetime(df['plmName'])
    df['period'] = df['plmName']
    df = df.drop(columns=['plmName'])
    df['periodicity'] = df['periodicity'].str.upper()
    df['source'] = 'GFI'

    #rename periodicity to periodType
    df = df.rename(columns={'periodicity':'periodType'})
    #rename route to instrument
    df = df.rename(columns={'route':'instrument'})

    df['date'] = date_obj

    df = df[['source','periodType','date','instrument','period','uom','value']]
    return df

def main(file):
    df = readFile(file)
    return df

if __name__ == '__main__':
    df = main('2024-03-14.xlsx') 
    print(df)