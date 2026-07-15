"""Shared Outlook download loop for both broker pipelines (csv + xlsx).

Both pipelines read the same `gfi` Inbox subfolder and differ only in which
attachment they save and where. Files are named by the report's true internal
date (see report_date), amendments overwrite the date they correct, plain
resends of an already-saved date are skipped, and nothing is ever written under
a non-`YYYY-MM-DD` name."""

import os
import datetime

import win32com.client

from utils.report_date import report_datestr, is_amendment


def _to_local(dt):
    """pywin32 ReceivedTime -> naive local datetime (matches Restrict's basis)."""
    return datetime.datetime.fromtimestamp(dt.timestamp())


def download_reports(subfolder, ext, attachment_match, dayStart, since=None):
    """Download this pipeline's attachments from the `gfi` Outlook subfolder.

    `subfolder`/`ext` place and name the output (e.g. 'csv'/'.csv'); the file is
    named `<internal-date><ext>`. `attachment_match(filename) -> bool` selects
    this pipeline's attachment. If `since` (a naive-local cursor) is given, only
    mail from ~1 day before it is examined; otherwise the last `dayStart` days.
    Returns (new_files, latest_seen); latest_seen is the newest ReceivedTime
    among messages accounted for, used to advance the caller's cursor."""
    new_files = []
    latest_seen = None
    dest_dir = os.path.join(os.getcwd(), './data', subfolder)
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

        for message in messages:
            received = _to_local(message.ReceivedTime)
            datestr = report_datestr(message)
            if datestr is None:
                # no xlsx / unparseable date -> never write a non-date filename
                print(f"Skipping (no valid report date): {message.Subject!r}")
                continue

            filename = f"{datestr}{ext}"
            fullname = os.path.join(dest_dir, filename)
            amendment = is_amendment(message.Subject)
            exists = os.path.exists(fullname)

            # account for every message we examined (advances the cursor)
            if latest_seen is None or received > latest_seen:
                latest_seen = received

            # plain resend of a date we already have -> skip; amendments overwrite
            if exists and not amendment:
                continue

            saved = False
            for attachment in message.Attachments:
                if attachment_match(attachment.FileName):
                    try:
                        verb = 'Overwriting' if exists else 'Saving'
                        tag = ' [amendment]' if amendment else ''
                        print(f'{verb} file{tag}: {fullname}')
                        attachment.SaveAsFile(fullname)
                        saved = True
                    except Exception as e:
                        print(f'Error processing attachment: {e}')
                    break

            if saved and filename not in new_files:
                new_files.append(filename)

    except Exception as e:
        print(f'Error accessing Outlook: {e}')

    return new_files, latest_seen
