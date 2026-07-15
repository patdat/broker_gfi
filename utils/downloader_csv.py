"""Download broker CSV attachments (GFI format) from the `gfi` Outlook folder.

Files are named by the report's true internal date (read from the xlsx that
arrives in the same email), not the subject line. See utils/outlook_download.py
for the shared loop and utils/report_date.py for date resolution."""

from utils.outlook_download import download_reports


def _is_csv_attachment(filename):
    return filename.startswith('GFI Bra') and filename.endswith('.csv')


def downloader(dayStart, since=None):
    return download_reports('csv', '.csv', _is_csv_attachment, dayStart, since)


def main(dayStart, since=None):
    return downloader(dayStart, since)


if __name__ == '__main__':
    main(3)
