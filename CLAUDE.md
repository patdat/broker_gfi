# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

A Windows-only, Outlook-driven ETL job for daily tanker-freight broker quotes (GFI / Braemar). It pulls two attachments out of a local Outlook folder, normalizes them, appends to two master CSVs, and publishes to AWS S3 plus the `K:\plm_prices` share. It feeds freight-rate data for crude trading.

Not a package: no `pyproject.toml`, no `uv.lock`, no tests, no CI, no linter — just `main.py` + `utils/` and a pinned `requirements.txt`.

## Running

Run from the repo root; every path is relative (`./data`, `./lookup`, `./logs`).

```bash
python main.py                     # normal: cursor + once-per-day gate; only genuinely new reports processed
python main.py --force             # ignore data/state.json (cursor) AND the once-per-day gate; re-scan the window
python main.py --force --days 30   # widen the look-back (gap recovery after an outage)
```

`--force` still respects the on-disk guard, so it won't re-download dates already saved, but it **always re-publishes the current master** to S3 and K: even when no new rows result (the master file itself is only rewritten when there genuinely are new rows).

**Every run has live side effects** — it reads Outlook, rewrites `data/`, uploads to S3 and copies to `K:`. There is no dry-run flag.

There is **no `.venv/` in this repo**; it runs on the machine's global Python 3.13 (Anaconda), which already has the pinned versions. To create one anyway:
`python -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt`

`requirements.txt` is pinned for Python 3.13: `pandas`, `numpy`, `openpyxl`, `pywin32`, `boto3`, `python-dotenv`.

### Prerequisites

- **Windows with the Outlook desktop client signed in** to the mailbox that receives the broker mail. `utils/outlook_download.py` drives MAPI through `win32com.client`; anywhere else the Outlook call fails (caught and logged) and nothing downloads.
- Mail must be filed into the **`gfi` Inbox subfolder** — `GetDefaultFolder(6).Folders["gfi"]`. The root Inbox is never scanned (this was the original "nothing downloads" bug).
- `.env` must hold `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET` (see `.env.example`). **There is currently no `.env` in this working tree**, so uploads fail fast and print `Cloud upload skipped` — local files are still produced. `utils/cloud.py` reads the vars with `os.environ[...]` at import, and that import is deliberately lazy and wrapped, which is why the missing-credentials error is swallowed.
- No Windows Scheduled Task for this job is registered on this machine — it is invoked manually here; check the production box for the real schedule.
- `notebook.ipynb` mirrors an **older** `main.py` (no cursor, no change detection). `main.py` is the source of truth.

## Architecture

Two near-identical pipelines run per invocation — **CSV** (GFI format) and **XLSX** (Braemar format) — both orchestrated in `main.py`. Both attachments arrive on the *same* email.

1. **Download** (`utils/downloader_csv.py`, `utils/downloader_xlsx.py` → shared loop in `utils/outlook_download.py`) — query the `gfi` folder for mail newer than the cursor (or the last `--days` when there is no cursor). CSV selects attachments named `GFI Bra*.csv`; XLSX selects `Braemar*.xlsx`. Files are written as `./data/{csv,xlsx}/<report-date>.{csv,xlsx}`. Returns `(new_files, latest_seen)`.
2. **Parse** (`utils/read_csv_file.py`, `utils/read_xlsx_file.py`) — `melt` each raw file to long format, keep only routes containing `TD` (dirty tanker routes; `na=False` so a blank trailing row can't crash it), and resolve period codes through `lookup/periods.csv`.
3. **Compile** (`csvCompiler` / `xlsxDownloader` in `main.py`) — parse only the newly downloaded files, concat onto the existing master, **dedupe on `['periodType','date','instrument','period']` keeping last**, rewrite. If no new rows result, a normal run skips the rewrite, upload and K: copy entirely.
4. **Publish** (`utils/shorten_csv.py::processBroker`) — writes `data/shortened/<name>_{last,60,30}.csv`, then uploads the master plus all three windows to `s3://<AWS_S3_BUCKET>/BROKER/MASTER/`.
5. **K: mirror** (`main.py::copyToKDrive`) — **only the xlsx pipeline** mirrors; it copies `GFI_xlsx.csv` and `GFI_xlsx_last.csv` to `K:\plm_prices`. The csv pipeline never touches K:. Skipped with a log line when the drive isn't mounted.
6. **Logging** (`utils/logger.py::setup_logging`) — tees stdout+stderr to `./logs/run_<YYYY-MM-DD_HHMMSS>.log`, one file per invocation.

### File naming comes from the xlsx's *internal* date, not the subject (`utils/report_date.py`)
This is the single most important non-obvious rule here. The subject line is unreliable — the broker mislabels sends and files amendments under the wrong date — so `report_datestr()` saves the `Braemar*.xlsx` attachment to a temp file, reads the trading date out of **cell row 3 / col 1** (`df.iloc[2, 0]`), and uses that `YYYY-MM-DD` for **both** pipelines' filenames. Consequences:

- If the date can't be resolved the message is **skipped entirely** and nothing is written — `_DATE_RE` guarantees no non-`YYYY-MM-DD` filename ever hits disk.
- A csv can therefore only be saved when its sibling xlsx is present and parseable.
- Subjects matching `\b(correction|amendment)\b` (`is_amendment`) **overwrite** the date they correct; a plain resend of a date already on disk is skipped.
- Reading the date means an extra `SaveAsFile` + `read_excel` per candidate message, so the Outlook scan is not free — that is why the cursor matters.

### Cursor (`data/state.json`)
`utils/state.py` keeps a per-pipeline high-water-mark (last processed email `ReceivedTime`) under keys `GFI_csvs` and `GFI_xlsx`. Each run asks Outlook only for mail newer than the cursor minus a 1-day margin. Git-ignored and self-healing; the on-disk check and the no-new-rows guard are the correctness nets, so the cursor can only *narrow* the query.

### Period normalization (`lookup/periods.csv`)
700 rows mapping a broker period code → `plmName` (a concrete date) and `periodicity`, which becomes the output `periodType`. Codes: `BITR`, `MTD`, `M`, `Q`, `A` (`H` is reserved; no data currently). `BITR`/`MTD` and any unmapped code fall back to the **beginning of the report month**. This file is the single source of truth for both the period dates and the `periodType` values, and both parse stages merge against it.

### The two masters have different schemas
- `data/GFI_csvs.csv`: `source, periodType, date, instrument, period, price` — **no `uom`, and the value column is `price`**.
- `data/GFI_xlsx.csv`: `source, periodType, date, instrument, period, uom, value`. The xlsx parser normalizes units (`WS`→`WSC`, `$/TONNE`→`PMT`) and special-cases `TD22`: its `BITR` value is divided by 1,000,000 and its `uom` forced to `LSM`.

Also note the csv master uses route codes like `TD3C` where the xlsx master uses `TD3` — they are not row-for-row comparable.

## Gotchas

- **Import-time side effects.** Merely importing these modules does real work from the *current working directory*: `main.py` calls `checkRunCondition()` at module level (line 35, reads `data/GFI_csvs.csv`), `utils/read_csv_file.py` and `utils/read_xlsx_file.py` read `lookup/periods.csv` at import, and `read_xlsx_file` also does an unused `os.listdir('./data/xlsx')`. Import from anywhere but the repo root and you get a `FileNotFoundError` before any of your code runs.
- **The once-per-day gate is keyed off the CSV master only.** `checkRunCondition()` compares today against `max(date)` in `GFI_csvs.csv` and gates *both* pipelines — if the xlsx master ever falls behind while the csv master is current, the run short-circuits and the xlsx side never catches up. Use `--force`.
- **`processBroker`'s `masterFolder='./data/master/'` argument is dead** — it is never read and `data/master/` does not exist. Extracts land in `data/shortened/`; `cloudFolder='BROKER/MASTER'` is the live S3 prefix.
- **Tracked vs ignored**: both masters, `data/shortened/*.csv` and `lookup/periods.csv` are committed and are the pipeline's persistent state. `data/csv/` and `data/xlsx/` raw downloads are also tracked. `data/state.json`, `.env`, `.venv/` and `logs/` are ignored.
- **Publishing rewrites the window CSVs and causes cosmetic float churn** (`296.60`→`296.6`) with no real data change. After a run, stage only the files you actually meant to change — don't `git add -A`.
- Stale `utils/__pycache__/*.cpython-311.pyc` files are checked into git even though the pins target 3.13; ignore them, they are not used.
