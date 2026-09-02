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

Three pipelines run per invocation — **CSV** (GFI format) and **XLSX** (Braemar format), which are near-identical, plus **JOSH** (Josh Smithson's "GFI FFA Curves" file), which shares the plumbing but has its own parser (see the JOSH subsection below). All are orchestrated in `main.py`. Built to be cheap on a schedule: a run with no new report makes one Outlook query and then does nothing (no downloads, no master rewrite, no upload).

1. **Download** (`utils/downloader_csv.py`, `utils/downloader_xlsx.py` — thin wrappers over the shared `utils/outlook_download.py`): read the `gfi` Inbox subfolder. Query only mail newer than the **cursor** (see below), or the last `dayStart` days when there is no cursor. **The report date is read from the xlsx's internal date cell (`utils/report_date.py`), never the email subject**, so both attachments in an email are named `<internal-date>.csv` / `.xlsx`. A date already on disk is skipped, **except** an amendment/correction (subject matches `correction|amendment`), which overwrites that date and re-compiles. **Nothing is written unless the name is a bare `YYYY-MM-DD`** (unparseable date → logged skip). CSV matches attachments starting `GFI Bra`; XLSX those starting `Braemar`. Returns `(new_files, latest_seen)`.
2. **Parse** (`utils/read_csv_file.py`, `utils/read_xlsx_file.py`): reshape each raw file into long format (`melt`), keep only routes containing `TD` (dirty tanker routes; filtered with `na=False` so a blank/trailing row can't crash it), and resolve period codes via the lookup (below).
3. **Compile** (`csvCompiler` / `xlsxDownloader` in `main.py`): parse only the newly downloaded files, concat onto the existing master, **dedupe on `['periodType','date','instrument','period']` keeping the last row**, and rewrite the master. **If no new rows result, a normal run skips the rewrite, upload, and K: copy entirely** (change-aware). Under `--force`, the master is still not rewritten when there are no new rows, but the existing master is re-published to S3 and K: anyway.
4. **Shorten + publish** (`utils/shorten_csv.py::processBroker`): write the most-recent-date (`_last`) and 30/60-day trailing windows to `./data/shortened/<name>_{last,30,60}.csv`, then upload the master and all three windows to `s3://<AWS_S3_BUCKET>/BROKER/MASTER/` via `utils/cloud.py`. Cloud errors are non-fatal (logged; pipeline continues).
5. **K: export** (`main.py::copyToKDrive`): after a successful **xlsx** update, copy `GFI_xlsx.csv` and `GFI_xlsx_last.csv` to `K:\plm_prices`. Silently skipped if the drive isn't mounted (machine-specific sink); per-file copy errors are caught.
6. **Logging** (`utils/logger.py::setup_logging`): every `python main.py` invocation tees stdout+stderr to `./logs/run_<YYYY-MM-DD_HHMMSS>.log`; folder auto-created.

### JOSH pipeline (`GFI_josh.csv`) — the third feed
Ingests Josh Smithson's daily **"GFI FFA Curves"** email (`josh.smithson@braemar.com`), whose single data attachment is `Curves DDMMYY.xlsx`. An Outlook rule files his mail into the same **`gfi` subfolder** the other two scan, so all three coexist there; the pipelines don't collide because each matches its own attachment (`GFI Bra*` / `Braemar*` / `Curves*.xlsx`) and each has its own date resolver that returns None for the others' mail.

- **Download** (`utils/downloader_josh.py`): reuses the shared `download_reports` loop via a new `date_resolver` hook (default = the Braemar `iloc[2,0]` behavior; josh passes `josh_report_datestr`). **Josh's report date is cell `iloc[0,0]`** of the Curves file (not `iloc[2,0]`). Files saved to `data/josh/<YYYY-MM-DD>.xlsx`; cursor key `GFI_josh`.
- **Parse** (`utils/read_josh_file.py`): the Curves file is transposed vs. the Braemar xlsx (instruments across columns, tenors down rows) and stacks two curve blocks — **World Scale** (`uom=WSC`) and **USD/Tonne** (`uom=PMT`) — plus a `WSFR` flat-rate row and a `Linked` **BITR** table. Keeps a curated instrument set via **`lookup/josh_instruments.csv`** (`header,instrument,lsm`). Directly-normalized routes: `TD3 C`→`TD3C`, `TD20 inc`→`TD20`, plus `TD8`, `TD19`, `TD22`, `TD28`. Three routes are taken from a **differently-based column** because the broker's own same-named column uses a wrong flat-rate basis (and prints junk near month-end):
- **`TD7`** ← **`X-UK Cont P.`** (WSFR 10.63; the raw `TD7` column, WSFR 10.13, is **dropped**).
- **`TD25`** ← **`USG AFRA Inc`** (the raw `TD25 inc` column is **dropped** — same series bar the flat-rate basis, and it printed a `-290.25` Balmo on `2026-08-27`).
- **`TD25E`** ← **`USG Afra Exc`**.

The dropped columns (`TD7`, `TD25 inc`) and their near-duplicate partners differ only by flat rate; the relabeled column is the correct series. Everything else (TC*, BLPG*) dropped. **BITR** for `TD7`/`TD25` still comes from the `Linked` table's `TD7`/`TD25` rows (X-UK / USG Afra have no Linked entry); `TD25E` gets no BITR. Month-range strips (`Aug-Dec'26`) are dropped. `TD22`/`TD28` are `uom=LSM` in the WS block (no division — they're already at LSM scale there); **only the `Linked`-table BITR value for `TD22` is ÷1e6** (it's reported in raw millions there). Values are taken as **magnitude** (`abs`): freight rates are always positive, so a negative is a broker sign-flip bad print (seen in **month-end Balmo**, e.g. TD25 `2026-08-27` printed `-290.25`). On the **last effective trading day of the month** the Balmo comes through **blank** for the TD routes (e.g. `2026-08-28` — the Fri before the 8/31 UK Summer Bank Holiday, so 8/28 was effectively month-end with no balance-of-month left to average). Those rows are legitimately absent (NaN dropped), **not** an error or a missing report — don't chase them. Watch for UK bank holidays shifting which day is the last one.
- **Compile + publish** (`main.py::joshDownloader`, seeded once by `seedJoshMaster`): same change-aware compile as xlsx, then full publish (shortened windows + S3 + K: copy of `GFI_josh.csv` / `GFI_josh_last.csv`). No MTD carry-over (that's xlsx-only).
- **New codes:** `periodType` adds `BAL` (real balance-of-month, dated to the first of the report month — the csv/xlsx feeds lack it) and `WSFR`; `uom` adds `LSM` and `WSFR`. **Dedupe key includes `uom`** (`['periodType','date','instrument','period','uom']`) since josh carries the same quote in multiple units.

### Cash-arb parquet (`utils/cash_arb.py` → `gfi_cash_arb.parquet`)
A compact, pivoted TD7/TD25-only export for downstream arb work, rebuilt at the end of every gated run (after all three pipelines) by `build_cash_arb()`. It reads the **xlsx** and **josh** masters fresh, keeps only the `TD7` and `TD25` routes, and **pivots the `instrument` column into two value columns** (`TD7`, `TD25`) — dropping `source` and shrinking ~1.5 MB CSVs to a ~35 KB parquet. Schema: `periodType, date, period, uom, TD7, TD25`. **`MTD` rows are dropped** (`DROP_PERIODTYPES`) — it's xlsx-only (josh uses `BAL`), so it only appeared on pre-josh dates and made a boundary seam. The two masters are merged with **josh taking precedence by report `date`**: any date josh covers is taken entirely from josh (xlsx rows for that date dropped); xlsx supplies the longer history before josh's start. Pivot key `['periodType','date','period','uom']` is collision-free in both masters. Written to `./data/gfi_cash_arb.parquet` and uploaded to `s3://<AWS_S3_BUCKET>/BROKER/MASTER/gfi_cash_arb.parquet` via `utils/cloud.py::upload_file` (cloud errors non-fatal). Requires `pyarrow` (pinned in `requirements.txt`).

### Incremental cursor (`data/state.json`)
`utils/state.py` stores a per-pipeline high-water-mark (last processed email `ReceivedTime`) in `data/state.json` (git-ignored, self-healing). Each run asks Outlook only for mail newer than the cursor (minus a 1-day safety margin), so a quiet tick returns nothing and exits fast. The on-disk check and the "no new rows" guard are the correctness nets — the cursor only *narrows* the query and can never cause a report to be skipped.

### Period normalization (`lookup/periods.csv`)
Maps broker period codes → `plmName` (concrete date) and `periodicity`, which becomes the output `periodType`. Codes: `BITR`, `MTD`, `M` (monthly), `Q` (quarterly), `A` (annual); `H` (half-year) is reserved for future data (none currently). Codes with no mapping — and `BITR`/`MTD` — fall back to the **beginning of the report month**. This lookup is the single source of truth both for dating quote labels **and for the `periodType` codes** (change a code here and it propagates to both pipelines); both parse stages merge against it.

### Output schemas (they differ between pipelines)
- CSV master: `source, periodType, date, instrument, period, price`
- XLSX master: `source, periodType, date, instrument, period, uom, value` (retains unit-of-measure; the XLSX parser normalizes units — `WS`→`WSC`, `$/TONNE`→`PMT` — and special-cases `TD22` to `LSM`).
- JOSH master (`GFI_josh.csv`): same columns as XLSX — `source, periodType, date, instrument, period, uom, value` — but a wider vocab (`periodType` adds `BAL`/`WSFR`, `uom` adds `WSFR`) and a 5-key dedupe including `uom`. See the JOSH pipeline subsection above.

### Run gating (two layers, for cheap scheduled runs)
1. `checkRunCondition()` — a cheap once-per-day guard: the pipelines run only when `today > max(date)` in `GFI_csvs.csv` (keyed off the **CSV** master, which also gates XLSX and JOSH). Once today's report is ingested, further runs that day skip without opening Outlook.
2. The **cursor** + **new-file-on-disk** + **no-new-rows** checks (above) make any run that *does* open Outlook cheap when nothing has changed.

## Gotchas

- **The download loop scans BOTH the root Inbox and its `gfi` subfolder** (`utils/outlook_download.py::_source_folders`). Broker mail used to be filed reliably into `gfi`, but as of ~2026-08-18 the real data emails (both the Braemar Market Report and the xlsx-bearing Curves email) started landing in the **root Inbox** instead, so scanning `gfi` alone silently stalled all three feeds at 8/17. Root is scanned first; a report present in both folders is taken from root and the `gfi` copy is skipped by the on-disk guard.
- **A DLP/mail-flow process ships a stripped copy of the Curves email into `gfi`** — subject gains `- Personal Use Only – Not for Redistribution`, the `Curves*.xlsx` is removed, and the inline image is re-encoded as `img1.png`. These have no usable attachment; the loop's per-pipeline attachment pre-filter skips them silently. The **intact** Curves xlsx is the clean copy in the root Inbox.
- **The loop only acts on messages carrying the pipeline's own attachment** (`attachment_match`); everything else in the (now root-wide) scan is skipped without a log line. A `Skipping (no valid report date)` line therefore means a real candidate whose date cell wouldn't parse — worth investigating.
- **File dates come from the xlsx's internal date cell (`iloc[2,0]`), not the email subject** (`utils/report_date.py`). The subject is unreliable — the broker mislabels sends (a Monday report subject-dated the next day) and files amendments under a different date than the original. Both pipelines name files by this internal date (the csv + xlsx arrive in the same email, and only the xlsx states the real date). A `YYYY-MM-DD` guard means a bad subject can never produce a stray filename (the old `Amendment).csv` / `orrection).csv` crash). **An amendment/correction (subject matches `correction|amendment`) supersedes: it overwrites that date's file and re-compiles**; a plain resend of a date already on disk is skipped.
- **K: files can be locked by a downstream consumer/Excel** on the network share — the copy then fails with `PermissionError [WinError 32]` (non-fatal, logged). It **won't self-heal**: a normal run sees the master current and skips the copy. Free the file, then re-copy manually or re-run `python main.py --force`.
- **`processBroker`'s `masterFolder='./data/master/'` argument is vestigial** — `./data/master/` isn't written to; `shorten_csv.py` writes under `./data/shortened/` and uploads to S3. `cloudFolder='BROKER/MASTER'` is the live S3 prefix. (An earlier version uploaded to Aliyun OSS; that path is gone.)
- **`data/state.json` (cursor), `.env` (secrets), `.venv/`, and `logs/` are git-ignored.** The cursor and logs rebuild themselves; `.env` must exist locally for S3 uploads to work.
- Data CSVs under `./data/` are committed and are the pipeline's persistent state; the scripts read and overwrite them in place.
- **Re-writing `./data/shortened/*.csv` produces cosmetic float churn.** Any run that publishes (esp. `--force`) rewrites the window files, dropping trailing zeros (`296.60`→`296.6`) with no real data change. When committing after a run, add only the files you actually changed (e.g. `git add main.py CLAUDE.md`) — don't `git add -A` and sweep in the reformatted data CSVs.
- **`git push` can't authenticate from the tool shell** — it hangs on a credential prompt with no tty (`could not read Username for github.com`). Push from the interactive session instead: type `!git push`.
