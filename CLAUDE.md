# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows-only ETL pipeline that ingests daily tanker freight broker quotes (GFI / Braemar) from a local Outlook inbox, normalizes them, appends to master CSVs, and publishes the results to AWS S3 (and, on the production box, a `K:` network drive). It powers freight rate data for crude trading. There is no build system or test suite — it is a small collection of pandas scripts driven by `main.py`, designed to be run on a schedule (e.g. hourly).

## Running

```bash
python main.py                 # normal: cursor + once-per-day gate; only genuinely new reports processed
python main.py --force         # ignore data/state.json (cursor) AND the once-per-day gate; re-scan the window
python main.py --force --days 30   # same, but widen the look-back to 30 days (gap recovery after an outage)
```

- **CLI flags** (`main.py`): `--force` bypasses the `state.json` cursor (`since=None`) and the once-per-day run gate; `--days N` sets the look-back window (default 5). `--force` still respects the on-disk guard, so it won't re-download dates already saved, but it **always re-publishes the current master** — S3 upload + K: copy run even when no new rows result (the master file itself is only rewritten to disk when there actually are new rows). A normal (non-force) run still skips the upload entirely when nothing changed.
- **Must run on Windows with Outlook installed and signed in** to the mailbox that receives the broker emails. The downloaders use `win32com.client` over MAPI and read the **`gfi` subfolder of the Inbox** (`GetDefaultFolder(6).Folders["gfi"]`) — broker emails are filed there, not the root Inbox. On any other environment the Outlook call fails (caught and logged) and no files are downloaded.
- All paths are relative (`./data`, `./lookup`), so **always run from the repo root**.
- **AWS credentials** for the S3 upload come from a local `.env` (see `.env.example`): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET`. `.env` is git-ignored — never commit it.
- Each util file has an `if __name__ == '__main__'` block for exercising one stage in isolation, e.g. `python utils/read_csv_file.py` (edit the hardcoded sample filename inside first).
- `notebook.ipynb` mirrors an **older** version of `main.py` (no cursor / change-detection); treat `main.py` as the source of truth.

### Dependencies
Pinned in `requirements.txt` (Python 3.13). Setup: `python -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt`.
Runtime deps: `pandas`, `numpy`, `openpyxl`, `pywin32`, `boto3`, `python-dotenv`.

## Architecture

Two parallel, near-identical pipelines run per invocation — **CSV** (GFI format) and **XLSX** (Braemar format) — orchestrated in `main.py`. Built to be cheap on a schedule: a run with no new report makes one Outlook query and then does nothing (no downloads, no master rewrite, no upload).

1. **Download** (`utils/downloader_csv.py`, `utils/downloader_xlsx.py` — thin wrappers over the shared `utils/outlook_download.py`): read the `gfi` Inbox subfolder. Query only mail newer than the **cursor** (see below), or the last `dayStart` days when there is no cursor. **The report date is read from the xlsx's internal date cell (`utils/report_date.py`), never the email subject**, so both attachments in an email are named `<internal-date>.csv` / `.xlsx`. A date already on disk is skipped, **except** an amendment/correction (subject matches `correction|amendment`), which overwrites that date and re-compiles. **Nothing is written unless the name is a bare `YYYY-MM-DD`** (unparseable date → logged skip). CSV matches attachments starting `GFI Bra`; XLSX those starting `Braemar`. Returns `(new_files, latest_seen)`.
2. **Parse** (`utils/read_csv_file.py`, `utils/read_xlsx_file.py`): reshape each raw file into long format (`melt`), keep only routes containing `TD` (dirty tanker routes; filtered with `na=False` so a blank/trailing row can't crash it), and resolve period codes via the lookup (below).
3. **Compile** (`csvCompiler` / `xlsxDownloader` in `main.py`): parse only the newly downloaded files, concat onto the existing master, **dedupe on `['periodType','date','instrument','period']` keeping the last row**, and rewrite the master. **If no new rows result, a normal run skips the rewrite, upload, and K: copy entirely** (change-aware). Under `--force`, the master is still not rewritten when there are no new rows, but the existing master is re-published to S3 and K: anyway.
4. **Shorten + publish** (`utils/shorten_csv.py::processBroker`): write the most-recent-date (`_last`) and 30/60-day trailing windows to `./data/shortened/<name>_{last,30,60}.csv`, then upload the master and all three windows to `s3://<AWS_S3_BUCKET>/BROKER/MASTER/` via `utils/cloud.py`. Cloud errors are non-fatal (logged; pipeline continues).
5. **K: export** (`main.py::copyToKDrive`): after a successful **xlsx** update, copy `GFI_xlsx.csv` and `GFI_xlsx_last.csv` to `K:\plm_prices`. Silently skipped if the drive isn't mounted (machine-specific sink); per-file copy errors are caught.
6. **Logging** (`utils/logger.py::setup_logging`): every `python main.py` invocation tees stdout+stderr to `./logs/run_<YYYY-MM-DD_HHMMSS>.log`; folder auto-created.

### Incremental cursor (`data/state.json`)
`utils/state.py` stores a per-pipeline high-water-mark (last processed email `ReceivedTime`) in `data/state.json` (git-ignored, self-healing). Each run asks Outlook only for mail newer than the cursor (minus a 1-day safety margin), so a quiet tick returns nothing and exits fast. The on-disk check and the "no new rows" guard are the correctness nets — the cursor only *narrows* the query and can never cause a report to be skipped.

### Period normalization (`lookup/periods.csv`)
Maps broker period codes → `plmName` (concrete date) and `periodicity`, which becomes the output `periodType`. Codes: `BITR`, `MTD`, `M` (monthly), `Q` (quarterly), `A` (annual); `H` (half-year) is reserved for future data (none currently). Codes with no mapping — and `BITR`/`MTD` — fall back to the **beginning of the report month**. This lookup is the single source of truth both for dating quote labels **and for the `periodType` codes** (change a code here and it propagates to both pipelines); both parse stages merge against it.

### Output schemas (they differ between pipelines)
- CSV master: `source, periodType, date, instrument, period, price`
- XLSX master: `source, periodType, date, instrument, period, uom, value` (retains unit-of-measure; the XLSX parser normalizes units — `WS`→`WSC`, `$/TONNE`→`PMT` — and special-cases `TD22` to `LSM`).

### Run gating (two layers, for cheap scheduled runs)
1. `checkRunCondition()` — a cheap once-per-day guard: the pipelines run only when `today > max(date)` in `GFI_csvs.csv` (keyed off the **CSV** master, which also gates XLSX). Once today's report is ingested, further runs that day skip without opening Outlook.
2. The **cursor** + **new-file-on-disk** + **no-new-rows** checks (above) make any run that *does* open Outlook cheap when nothing has changed.

## Gotchas

- **Broker emails live in the `gfi` Inbox subfolder**, not the root Inbox — the downloaders navigate to `GetDefaultFolder(6).Folders["gfi"]`. Scanning the root Inbox finds nothing (this was the "nothing downloads" bug).
- **File dates come from the xlsx's internal date cell (`iloc[2,0]`), not the email subject** (`utils/report_date.py`). The subject is unreliable — the broker mislabels sends (a Monday report subject-dated the next day) and files amendments under a different date than the original. Both pipelines name files by this internal date (the csv + xlsx arrive in the same email, and only the xlsx states the real date). A `YYYY-MM-DD` guard means a bad subject can never produce a stray filename (the old `Amendment).csv` / `orrection).csv` crash). **An amendment/correction (subject matches `correction|amendment`) supersedes: it overwrites that date's file and re-compiles**; a plain resend of a date already on disk is skipped.
- **K: files can be locked by a downstream consumer/Excel** on the network share — the copy then fails with `PermissionError [WinError 32]` (non-fatal, logged). It **won't self-heal**: a normal run sees the master current and skips the copy. Free the file, then re-copy manually or re-run `python main.py --force`.
- **`processBroker`'s `masterFolder='./data/master/'` argument is vestigial** — `./data/master/` isn't written to; `shorten_csv.py` writes under `./data/shortened/` and uploads to S3. `cloudFolder='BROKER/MASTER'` is the live S3 prefix. (An earlier version uploaded to Aliyun OSS; that path is gone.)
- **`data/state.json` (cursor), `.env` (secrets), `.venv/`, and `logs/` are git-ignored.** The cursor and logs rebuild themselves; `.env` must exist locally for S3 uploads to work.
- Data CSVs under `./data/` are committed and are the pipeline's persistent state; the scripts read and overwrite them in place.
- **Re-writing `./data/shortened/*.csv` produces cosmetic float churn.** Any run that publishes (esp. `--force`) rewrites the window files, dropping trailing zeros (`296.60`→`296.6`) with no real data change. When committing after a run, add only the files you actually changed (e.g. `git add main.py CLAUDE.md`) — don't `git add -A` and sweep in the reformatted data CSVs.
- **`git push` can't authenticate from the tool shell** — it hangs on a credential prompt with no tty (`could not read Username for github.com`). Push from the interactive session instead: type `!git push`.
