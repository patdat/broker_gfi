"""Resolve a broker report's true date and validate output filenames.

The email subject line is unreliable (the broker mislabels sends and files
amendments under the wrong date), but every email carries a `Braemar ...xlsx`
attachment whose sheet states the real trading date. That internal date is the
single source of truth for naming the files of *both* pipelines - the csv and
the xlsx arrive in the same email. Nothing is ever written to disk under a name
that isn't a bare `YYYY-MM-DD`."""

import os
import re
import tempfile
import warnings

import pandas as pd

# subjects flagged as (Amendment)/(Correction) always overwrite that date
_AMENDMENT_RE = re.compile(r'\b(?:correction|amendment)\b', re.IGNORECASE)
# the only filename shape we ever write
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

_XLSX_PREFIX = 'Braemar'
_XLSX_SUFFIX = '.xlsx'


def read_xlsx_date(path):
    """The report's own date, read from the Braemar xlsx (row-3, col-1 cell).

    Returns a pandas.Timestamp, or None if the file/cell can't be parsed."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')  # openpyxl "no default style" noise
            df = pd.read_excel(path, header=None)
        return pd.to_datetime(df.iloc[2, 0])
    except Exception:
        return None


def _xlsx_attachment(message):
    for attachment in message.Attachments:
        name = attachment.FileName
        if name.startswith(_XLSX_PREFIX) and name.endswith(_XLSX_SUFFIX):
            return attachment
    return None


def resolve_report_date(message):
    """Read the report's date from the message's xlsx attachment.

    Saves the xlsx to a temp file (win32com attachments can only be read via
    SaveAsFile), parses the internal date, and cleans up. Returns a
    pandas.Timestamp, or None when there's no xlsx attachment or it won't parse."""
    attachment = _xlsx_attachment(message)
    if attachment is None:
        return None
    fd, tmp = tempfile.mkstemp(suffix='.xlsx', prefix='gfi_probe_')
    os.close(fd)
    try:
        attachment.SaveAsFile(tmp)
        return read_xlsx_date(tmp)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def report_datestr(message):
    """Resolve the report date as a validated `YYYY-MM-DD` string, or None.

    None means: no xlsx attachment, an unparseable date, or a value that somehow
    doesn't format to a bare date. Callers MUST treat None as "save nothing" -
    this is the guard that stops garbage filenames from ever hitting disk."""
    date = resolve_report_date(message)
    if date is None:
        return None
    datestr = date.strftime('%Y-%m-%d')
    if not _DATE_RE.match(datestr):
        return None
    return datestr


def is_amendment(subject):
    """True when the subject marks an amendment/correction (case-insensitive)."""
    return bool(_AMENDMENT_RE.search(subject or ''))
