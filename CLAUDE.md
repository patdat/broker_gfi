# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows-only ETL pipeline that ingests daily tanker freight broker quotes (GFI / Braemar) from a local Outlook inbox, normalizes them, and appends to master CSVs. It powers freight rate data for crude trading. There is no build system, package manifest, or test suite — it is a small collection of pandas scripts driven by `main.py`.

## Running

```bash
python main.py          # runs main(5): processes the 5 most recent files per pipeline
```

- **Must run on Windows with Outlook installed and signed in** to the mailbox that receives the broker emails. The downloaders use `win32com.client` to read the inbox over MAPI (`GetDefaultFolder(6)` = Inbox). On any other environment the Outlook call fails and no files are downloaded.
- All paths are relative (`./data`, `./lookup`), so **always run from the repo root**.
- Each util file has an `if __name__ == '__main__'` block for exercising one stage in isolation, e.g. `python utils/read_csv_file.py` (edit the hardcoded sample filename inside first).
- `notebook.ipynb` mirrors `main.py` and is the interactive/debug entry point.

### Dependencies (no requirements file exists)
`pandas`, `numpy`, `pywin32` (`win32com`), `openpyxl` (for `pd.read_excel`).

## Architecture

Two parallel, near-identical pipelines run per invocation — **CSV** (GFI format) and **XLSX** (Braemar format) — orchestrated in `main.py`:

1. **Download** (`utils/downloader_csv.py`, `utils/downloader_xlsx.py`): scan Outlook messages received within the last `dayStart` days; save matching attachments to `./data/csv/<date>.csv` or `./data/xlsx/<date>.xlsx`. CSV matches attachments starting `GFI Bra`; XLSX matches those starting `Braemar`.
2. **Parse** (`utils/read_csv_file.py`, `utils/read_xlsx_file.py`): reshape each raw file into long format (`melt`), keep only routes containing `TD` (dirty tanker routes), and resolve period codes via the lookup (below).
3. **Compile** (`csvCompiler` / `xlsxDownloader` in `main.py`): concatenate the newly parsed frames onto the existing master (`./data/GFI_csvs.csv` or `./data/GFI_xlsx.csv`), **dedupe on `['periodType','date','instrument','period']` keeping the last row**, and rewrite the master.
4. **Shorten** (`utils/shorten_csv.py::processBroker`): write 30- and 60-day trailing windows to `./data/shortened/<name>_{30,60}.csv`.

### Period normalization (`lookup/periods.csv`)
Maps broker period codes → `plmName` (concrete date) and `periodicity` (`BITR`, `MTD`, `monthly`, `quarterly`, `yearly`). Codes with no mapping — and `BITR`/`MTD` — fall back to the **beginning of the report month**. This lookup is the single source of truth for turning quote labels into dated periods; both parse stages merge against it.

### Output schemas (they differ between pipelines)
- CSV master: `source, periodType, date, instrument, period, price`
- XLSX master: `source, periodType, date, instrument, period, uom, value` (retains unit-of-measure; the XLSX parser normalizes units — `WS`→`WSC`, `$/TONNE`→`PMT` — and special-cases `TD22` to `LSM`).

### Run gating
`checkRunCondition()` in `main.py` runs the pipelines only when `today > max(date)` in `GFI_csvs.csv` — a once-per-day guard keyed off the **CSV** master, which also gates the XLSX pipeline.

## Gotchas

- **Attachment filenames come from `message.Subject[-10:]`** (the last 10 chars, expected to be the `YYYY-MM-DD` date). Correction emails are meant to be skipped via a `\b(correction|CORRECTION)\b` regex, but subjects like `(correction)` can slip through and produce garbage files such as `orrection).csv` in `./data/csv|xlsx`. Watch for stray non-date filenames when parsing.
- **`processBroker`'s `masterFolder` / `cloudFolder='BROKER/MASTER'` arguments are vestigial** — the current `shorten_csv.py` writes only local files. An earlier version uploaded the masters and windows to Aliyun OSS (`pcia-crude.oss-us-east-1.aliyuncs.com/BROKER/MASTER/`, visible in `notebook.ipynb` output); that upload code is no longer in the repo. Do not assume outputs are published anywhere.
- Data CSVs under `./data/` are committed to the repo and are the pipeline's persistent state; the scripts read and overwrite them in place.
