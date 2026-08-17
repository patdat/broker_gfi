"""Download Josh Smithson's 'GFI FFA Curves' xlsx from the `gfi` Outlook folder.

Josh's mail is filed into the same `gfi` subfolder (Outlook rule). His report
date lives in the Curves file's own cell iloc[0,0], so this pipeline passes a
josh-specific date_resolver. Files are saved to ./data/josh/<internal-date>.xlsx."""

from utils.outlook_download import download_reports
from utils.report_date import josh_report_datestr


def _is_curves_attachment(filename):
    return filename.startswith('Curves') and filename.endswith('.xlsx')


def downloader(dayStart, since=None):
    return download_reports('josh', '.xlsx', _is_curves_attachment, dayStart, since,
                            date_resolver=josh_report_datestr)


def main(dayStart, since=None):
    return downloader(dayStart, since)


if __name__ == '__main__':
    main(3)
