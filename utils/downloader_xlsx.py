import os
import datetime
import win32com.client
import re

def downloader(dayStart):
    codePath = os.getcwd()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        inbox = outlook.GetDefaultFolder(6)
        codePath = os.getcwd()
        start_date = datetime.datetime.now() - datetime.timedelta(days=dayStart)
        messages = inbox.Items.Restrict(
            "[ReceivedTime] >= '{0}'".format(start_date.strftime("%m/%d/%Y %H:%M %p"))
        )
        lst_subject = []

        for message in messages:
            formatted_date = message.Subject[-10:]
            # Check if subject contains the words "correction" or "CORRECTION"
            if re.search(r'\b(?:correction|CORRECTION)\b', message.Subject):
                print(f"Skipping file saving for subject: {message.Subject}")
                continue
            for attachment in message.Attachments:
                try:
                    if attachment.FileName.startswith(
                        "Braemar"
                    ) and attachment.FileName.endswith(".xlsx"):
                        fullname = os.path.join(
                            codePath, "./data/xlsx", formatted_date + ".xlsx"
                        )
                        print(f"Saving file: {fullname}")
                        attachment.SaveAsFile(fullname)
                        lst_subject.append(formatted_date)
                except Exception as e:
                    print(f"Error processing attachment: {str(e)}")

    except Exception as e:
        print(f"Error accessing Outlook: {str(e)}")

def main (dayStart):
    downloader(dayStart)

if __name__ == "__main__":
    main(3)