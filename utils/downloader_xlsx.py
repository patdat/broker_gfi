"""Download broker XLSX attachments (Braemar format) from the `gfi` Outlook folder.

Files are named by the report's true internal date (the xlsx's own date cell),
not the subject line. See utils/outlook_download.py for the shared loop and
utils/report_date.py for date resolution."""

from utils.outlook_download import download_reports


def _is_xlsx_attachment(filename):
    return filename.startswith('Braemar') and filename.endswith('.xlsx')


def downloader(dayStart, since=None):
    return download_reports('xlsx', '.xlsx', _is_xlsx_attachment, dayStart, since)


def main(dayStart, since=None):
    return downloader(dayStart, since)


if __name__ == '__main__':
    main(3)
