import os
from dotenv import load_dotenv
import pandas as pd
import boto3
from io import StringIO, BytesIO

load_dotenv()

aws_bucket = os.environ['AWS_S3_BUCKET']
aws_server = 's3.amazonaws.com'
aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
aws_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']
            
class aws:
    """
    A class for uploading a DataFrame to Amazon S3 in CSV or Parquet format.

    Parameters:
    df (pd.DataFrame): The DataFrame to be uploaded.
    filepath (str): The S3 directory path where the file will be stored.
    filename (str): The name of the file in S3.
    file_format (str): Format to upload - 'csv' or 'parquet'.
    df_index (bool, optional): If True, include the DataFrame index in the uploaded data.
    """

    def __init__(self, df, filepath, filename, file_format='csv', df_index=False):
        # AWS credentials
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        
        # Initialize the AWS S3 resource
        self.s3_resource = boto3.resource('s3', 
                                         aws_access_key_id=self.aws_access_key_id, 
                                         aws_secret_access_key=self.aws_secret_access_key)
        
        # Store format
        self.file_format = file_format.lower()
        
        # Upload the DataFrame to S3
        self.upload_dataframe(df, filepath, filename, df_index)

    def upload_dataframe(self, df, filepath, filename, df_index):
        # S3 bucket and object path
        bucket = aws_bucket
        object_path = f"{filepath}/{filename}"
        
        if self.file_format == 'parquet':
            # Create a binary buffer for Parquet
            buffer = BytesIO()
            df.to_parquet(buffer, index=df_index)
            buffer.seek(0)  # Reset buffer position
            
            # Upload the Parquet data to S3
            self.s3_resource.Object(bucket, object_path).put(Body=buffer.getvalue())
            
        elif self.file_format == 'csv':
            # Create a text buffer for CSV
            csv_buffer = StringIO()
            df.to_csv(csv_buffer, index=df_index)
            
            # Upload the CSV data to S3
            self.s3_resource.Object(bucket, object_path).put(Body=csv_buffer.getvalue())
            
        else:
            raise ValueError(f"Unsupported file format: {self.file_format}. Use 'csv' or 'parquet'.")

        # Generate the shared link for the uploaded file
        server = aws_server
        self.shared_link = f"https://{bucket}.{server}/{object_path}"

    def __repr__(self):
        return f'AWS S3 ({self.file_format}): {self.shared_link}'
    
def cloud(df, filepath, filename, file_format='csv', df_index=False):
    """
    Upload a DataFrame to AWS S3 in specified format.
    
    Args:
        df (pd.DataFrame): The DataFrame to be uploaded.
        filepath (str): The directory path where the file will be stored.
        filename (str): The name of the file.
        file_format (str): Format to upload - 'csv' or 'parquet'.
        df_index (bool, optional): If True, include the DataFrame index in the uploaded data.
    """
    if file_format not in ['csv', 'parquet']:
        raise ValueError("file_format must be 'csv' or 'parquet'")
    
    aws_uploader = aws(df, filepath, filename, file_format, df_index)
    print(repr(aws_uploader))
    return aws_uploader

# Convenience functions for specific formats
def upload_csv(df, filepath, filename, df_index=False):
    """Upload DataFrame as CSV to S3."""
    return cloud(df, filepath, filename, file_format='csv', df_index=df_index)

def upload_parquet(df, filepath, filename, df_index=False):
    """Upload DataFrame as Parquet to S3."""
    return cloud(df, filepath, filename, file_format='parquet', df_index=df_index)

def upload_file(local_path, filepath, filename):
    """Upload a local file to S3 as-is (no pandas round-trip)."""
    object_path = f"{filepath}/{filename}"
    s3 = boto3.client(
        's3',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
    s3.upload_file(local_path, aws_bucket, object_path)
    shared_link = f"https://{aws_bucket}.{aws_server}/{object_path}"
    print(f'AWS S3 (file): {shared_link}')
    return shared_link

if __name__ == '__main__':
    import numpy as np
    
    # Test DataFrame
    df = pd.DataFrame(np.random.randint(0, 100, size=(100, 4)), columns=list('ABCD'))
    
    # Test CSV upload
    print("Testing CSV upload...")
    upload_csv(df, 'TEST/TEST', 'test.csv')
    
    # Test Parquet upload
    print("\nTesting Parquet upload...")
    upload_parquet(df, 'TEST/TEST', 'test.parquet')