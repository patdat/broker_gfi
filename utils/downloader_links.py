"""Download 'GFI FFA Curves' xlsx files from hyperlinks in the `gfi` Outlook folder.

Unlike the Braemar/GFI feeds, the FFA Curves report is NOT an email attachment:
the body carries a hyperlink (display text ``Curves DDMMYY.xlsx``) pointing at a
SendGrid click-tracking URL that 302-redirects to the actual xlsx. That tracking
URL is unique per email and changes constantly, so we extract it fresh from each
message, follow the redirect, and save the payload as ``./data/ffa/<YYYY-MM-DD>.xlsx``.

The report date comes from the subject's ``DDMMYY`` token (e.g. ``210726`` ->
``2026-07-21``), not the file contents. Several interim emails arrive per day
until a 'final' one supersedes them; we keep only the newest email per date, so a
single run downloads at most one file per date (a manual re-run re-downloads that
date - cheap, one GET, and always correct).

Download-only for now: no parsing, master, S3 or K: publish (a later stage). The
``(new_files, latest_seen)`` return matches the other downloaders so wiring this
into ``main.py`` with a ``GFI_ffa`` cursor later is trivial. Uses stdlib
``urllib`` (no new dependency); the magic-byte check makes a bad fetch (a landing
or login page instead of the file) a visible skip rather than saved junk."""

import os
import re
import datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen

import win32com.client

# subject filter - the DDMMYY suffix changes per report, so match only the stem
_SUBJECT_MATCH = 'gfi ffa curves'
# the 6-digit DDMMYY report-date token that follows 'Curves' in the subject
_DATE_TOKEN_RE = re.compile(r'curves\s+(\d{6})', re.IGNORECASE)
# the only filename shape we ever write
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
# xlsx is a zip archive; a real .xlsx payload starts with this local-file header
_XLSX_MAGIC = b'PK\x03\x04'
_USER_AGENT = 'Mozilla/5.0 (broker_gfi downloader)'
_TIMEOUT = 60


def _to_local(dt):
    """pywin32 ReceivedTime -> naive local datetime (matches Restrict's basis)."""
    return datetime.datetime.fromtimestamp(dt.timestamp())


def subject_datestr(subject):
    """Resolve the report date as a validated ``YYYY-MM-DD`` string, or None.

    Reads the ``DDMMYY`` token after 'Curves' in the subject. None means no such
    token or a value that isn't a real date - callers MUST treat None as "save
    nothing", the guard that keeps garbage filenames off disk."""
    if not subject:
        return None
    match = _DATE_TOKEN_RE.search(subject)
    if not match:
        return None
    try:
        date = datetime.datetime.strptime(match.group(1), '%d%m%y')
    except ValueError:
        return None
    datestr = date.strftime('%Y-%m-%d')
    if not _DATE_RE.match(datestr):
        return None
    return datestr


class _XlsxLinkParser(HTMLParser):
    """Collect ``(href, visible_text)`` for every anchor in an HTML body."""

    def __init__(self):
        super().__init__()
        self._href = None
        self._text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self._href = dict(attrs).get('href')
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href is not None:
            self.links.append((self._href, ''.join(self._text).strip()))
            self._href = None
            self._text = []


def extract_xlsx_link(html_body):
    """The href of the body's ``Curves ...xlsx`` hyperlink, or None.

    Picks the first anchor whose visible text mentions '.xlsx' (the SendGrid
    tracking URL); its display name is the file, its href the link to follow."""
    if not html_body:
        return None
    parser = _XlsxLinkParser()
    try:
        parser.feed(html_body)
    except Exception:
        return None
    for href, text in parser.links:
        if href and '.xlsx' in text.lower():
            return href
    return None


def fetch_xlsx(url):
    """GET ``url`` (following redirects) and return xlsx bytes, or None.

    Returns None on any network error or when the payload isn't a real xlsx
    (e.g. the link resolved to a landing/login page), so we never save junk."""
    try:
        request = Request(url, headers={'User-Agent': _USER_AGENT})
        with urlopen(request, timeout=_TIMEOUT) as response:
            data = response.read()
    except Exception as e:
        print(f'Error fetching xlsx link: {e}')
        return None
    if not data.startswith(_XLSX_MAGIC):
        print(f'Fetched content is not an xlsx (first bytes: {data[:8]!r}) - skipping')
        return None
    return data


def downloader(dayStart, since=None):
    """Download 'GFI FFA Curves' xlsx files from the `gfi` Outlook subfolder.

    Scans mail from ~1 day before ``since`` (if given) else the last ``dayStart``
    days, keeps the newest email per report date, extracts its xlsx hyperlink,
    follows the redirect and saves ``./data/ffa/<date>.xlsx`` (overwriting, so the
    final report supersedes interims). Returns ``(new_files, latest_seen)``;
    latest_seen is the newest ReceivedTime among matching messages examined."""
    new_files = []
    latest_seen = None
    dest_dir = os.path.join(os.getcwd(), './data', 'ffa')
    os.makedirs(dest_dir, exist_ok=True)
    try:
        outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        # broker emails are filed into the 'gfi' subfolder of the Inbox, not the root Inbox
        inbox = outlook.GetDefaultFolder(6).Folders["gfi"]
        if since is not None:
            start_date = since - datetime.timedelta(days=1)
        else:
            start_date = datetime.datetime.now() - datetime.timedelta(days=dayStart)
        messages = inbox.Items.Restrict(
            "[ReceivedTime] >= '{0}'".format(start_date.strftime("%m/%d/%Y %H:%M %p"))
        )

        # keep only the newest 'GFI FFA Curves' email per report date (interims
        # are superseded by the final send that day)
        newest = {}  # datestr -> (received, message)
        for message in messages:
            subject = message.Subject or ''
            if _SUBJECT_MATCH not in subject.lower():
                continue

            received = _to_local(message.ReceivedTime)
            # account for every matching message (advances the caller's cursor)
            if latest_seen is None or received > latest_seen:
                latest_seen = received

            datestr = subject_datestr(subject)
            if datestr is None:
                print(f'Skipping (no valid report date): {subject!r}')
                continue
            if datestr not in newest or received > newest[datestr][0]:
                newest[datestr] = (received, message)

        for datestr, (received, message) in sorted(newest.items()):
            href = extract_xlsx_link(message.HTMLBody)
            if href is None:
                print(f'Skipping (no xlsx link in body): {message.Subject!r}')
                continue
            data = fetch_xlsx(href)
            if data is None:
                continue

            filename = f'{datestr}.xlsx'
            fullname = os.path.join(dest_dir, filename)
            verb = 'Overwriting' if os.path.exists(fullname) else 'Saving'
            print(f'{verb} file: {fullname}')
            with open(fullname, 'wb') as f:
                f.write(data)
            if filename not in new_files:
                new_files.append(filename)

    except Exception as e:
        print(f'Error accessing Outlook: {e}')

    return new_files, latest_seen


def main(dayStart, since=None):
    return downloader(dayStart, since)


if __name__ == '__main__':
    files, latest = main(5)
    print(f'Downloaded: {files}; latest seen: {latest}')
