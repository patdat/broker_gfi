
import os
import datetime
import win32com.client
import re


def _to_local(dt):
    """pywin32 ReceivedTime -> naive local datetime (matches Restrict's basis)."""
    return datetime.datetime.fromtimestamp(dt.timestamp())


def downloader(dayStart, since=None):
    """Download broker XLSX attachments, skipping dates already on disk.

    If `since` (a naive-local datetime cursor) is given, only look at mail from
    ~1 day before it; otherwise fall back to the last `dayStart` days. Returns
    (new_files, latest_seen) where latest_seen is the newest ReceivedTime among
    messages we accounted for (downloaded or already had) - used to advance the
    caller's cursor. A 1-day margin plus the on-disk check make the cursor safe:
    it can never skip a report, only narrow the query."""
    new_files = []
    latest_seen = None
    codePath = os.getcwd()
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
            # skip correction emails
            if re.search(r'\b(?:correction|CORRECTION)\b', message.Subject):
                print(f"Skipping file saving for subject: {message.Subject}")
                continue
            formatted_date = message.Subject[-10:]
            filename = formatted_date + ".xlsx"
            fullname = os.path.join(codePath, "./data/xlsx", filename)
            received = _to_local(message.ReceivedTime)
            if os.path.exists(fullname):
                # already have this date; count it toward the cursor, download nothing
                if latest_seen is None or received > latest_seen:
                    latest_seen = received
                continue
            for attachment in message.Attachments:
                try:
                    if attachment.FileName.startswith(
                        "Braemar"
                    ) and attachment.FileName.endswith(".xlsx"):
                        print(f"Saving file: {fullname}")
                        attachment.SaveAsFile(fullname)
                        new_files.append(filename)
                        if latest_seen is None or received > latest_seen:
                            latest_seen = received
                except Exception as e:
                    print(f"Error processing attachment: {str(e)}")

    except Exception as e:
        print(f"Error accessing Outlook: {str(e)}")

    return new_files, latest_seen


def main(dayStart, since=None):
    return downloader(dayStart, since)


if __name__ == "__main__":
    main(3)
