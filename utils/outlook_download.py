"""Shared Outlook download loop for all three broker pipelines (csv + xlsx + josh).

Scans BOTH the root Inbox and its `gfi` subfolder — the broker's mail-flow moved
from reliably filing into `gfi` to sometimes delivering straight to the root
Inbox (and a DLP process ships stripped, xlsx-less copies of the Curves email
into `gfi`), so a single folder can't be trusted. Each pipeline is selected by
its own attachment (`attachment_match`); messages that don't carry it are
skipped silently, which also ignores the stripped copies. Files are named by the
report's true internal date (see report_date), amendments overwrite the date
they correct, plain resends of an already-saved date are skipped, and nothing is
ever written under a non-`YYYY-MM-DD` name."""

import os
import datetime

import win32com.client

from utils.report_date import report_datestr, is_amendment

_OL_MAIL = 43  # olMail item class; skip calendar/report/other items in the root Inbox


def _to_local(dt):
    """pywin32 ReceivedTime -> naive local datetime (matches Restrict's basis)."""
    return datetime.datetime.fromtimestamp(dt.timestamp())


def _source_folders(outlook):
    """The folders to scan, in order: root Inbox first, then its `gfi` subfolder.

    Root first means a report present in both folders is saved from the root copy
    and the `gfi` copy is skipped by the on-disk guard. The `gfi` subfolder may
    not exist on every machine."""
    root = outlook.GetDefaultFolder(6)
    folders = [root]
    try:
        folders.append(root.Folders["gfi"])
    except Exception:
        pass
    return folders


def download_reports(subfolder, ext, attachment_match, dayStart, since=None, date_resolver=None):
    """Download this pipeline's attachments from the root Inbox and `gfi` subfolder.

    `subfolder`/`ext` place and name the output (e.g. 'csv'/'.csv'); the file is
    named `<internal-date><ext>`. `attachment_match(filename) -> bool` selects
    this pipeline's attachment; a message not carrying it is skipped silently. If
    `since` (a naive-local cursor) is given, only mail from ~1 day before it is
    examined; otherwise the last `dayStart` days. `date_resolver(message) -> str |
    None` resolves the report date; defaults to the Braemar `report_datestr` when
    not given. Returns (new_files, latest_seen); latest_seen is the newest
    ReceivedTime among messages accounted for, used to advance the caller's cursor."""
    if date_resolver is None:
        date_resolver = report_datestr  # existing Braemar-xlsx behavior
    new_files = []
    latest_seen = None
    dest_dir = os.path.join(os.getcwd(), './data', subfolder)

    if since is not None:
        start_date = since - datetime.timedelta(days=1)
    else:
        start_date = datetime.datetime.now() - datetime.timedelta(days=dayStart)
    restrict = "[ReceivedTime] >= '{0}'".format(start_date.strftime("%m/%d/%Y %H:%M %p"))

    def _process(message):
        nonlocal latest_seen
        # only consider messages carrying this pipeline's attachment; this skips
        # unrelated inbox mail and the DLP-stripped Curves copies silently
        try:
            attachments = list(message.Attachments)
        except Exception:
            return
        if not any(attachment_match(a.FileName) for a in attachments):
            return

        received = _to_local(message.ReceivedTime)
        datestr = date_resolver(message)
        if datestr is None:
            # has the attachment but the date won't resolve -> never write a bad name
            print(f"Skipping (no valid report date): {message.Subject!r}")
            return

        filename = f"{datestr}{ext}"
        fullname = os.path.join(dest_dir, filename)
        amendment = is_amendment(message.Subject)
        exists = os.path.exists(fullname)

        # account for every candidate we examined (advances the cursor)
        if latest_seen is None or received > latest_seen:
            latest_seen = received

        # plain resend of a date we already have -> skip; amendments overwrite
        if exists and not amendment:
            return

        for attachment in attachments:
            if attachment_match(attachment.FileName):
                try:
                    verb = 'Overwriting' if exists else 'Saving'
                    tag = ' [amendment]' if amendment else ''
                    print(f'{verb} file{tag}: {fullname}')
                    attachment.SaveAsFile(fullname)
                    if filename not in new_files:
                        new_files.append(filename)
                except Exception as e:
                    print(f'Error processing attachment: {e}')
                break

    try:
        outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        for folder in _source_folders(outlook):
            try:
                messages = folder.Items.Restrict(restrict)
            except Exception as e:
                print(f'Restrict error on {getattr(folder, "Name", "?")!r}: {e}')
                continue
            for message in messages:
                try:
                    if message.Class != _OL_MAIL:
                        continue
                except Exception:
                    continue
                _process(message)

    except Exception as e:
        print(f'Error accessing Outlook: {e}')

    return new_files, latest_seen
