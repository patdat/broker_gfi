# Design: Josh Curves pipeline → `GFI_josh.csv`

Date: 2026-08-17

## Goal

Add a third ETL pipeline to `main.py`, alongside the existing CSV (GFI) and XLSX
(Braemar) pipelines, that ingests Josh Smithson's daily **"GFI FFA Curves"**
email (`josh.smithson@braemar.com`), parses the `Curves DDMMYY.xlsx` attachment,
and produces/publishes a new master `data/GFI_josh.csv`.

This feed carries the same underlying quotes as the existing Braemar xlsx but in
a fuller layout — more forward tenors (quarters, cals, a real Balmo) and both
World Scale and USD/Tonne values. It replaces a previously fragile ingestion of
the same email.

## Source file shape (`Curves DDMMYY.xlsx`)

Single sheet, read with `header=None`. Radically different from the Braemar xlsx
(`read_xlsx_file.py`) — do NOT reuse that parser.

- `iloc[0,0]` = **report date** (e.g. `2026-08-17`). This is the file's own date
  cell and the single source of truth for naming/dating (subject is unreliable).
- Row 0, cols 1..27 = **instrument headers** (`TD3 C`, `TD20 inc`, `TD7`, `TD8`,
  `TC2 inc`, … `BLPG1 ($/t)`, `TD22`, `USG Afra Exc`, `TD28`).
- Col 0, rows 1..44 = **tenor labels**, stacked into two curve blocks:
  - **Block 1 — World Scale (rows 1–20):** `Balmo` (row 1), 8 forward months as
    real dates (rows 2–9), 7 quarters `Q4-26`… (rows 10–16), a strip
    `Aug-Dec'26` (row 17), Cals `Cal-27/28/29` (rows 18–20).
  - **Block 2 — USD/Tonne (rows 25–44):** same tenor structure, `USD/Tonne`
    header at row 24.
- **`WSFR 2026` flat rates — row 22, col-per-instrument.** One flat-rate value
  per instrument (same column layout as the curve blocks). **Ingested** (see
  WSFR below).
- **`Linked` table — rows 49–95, ROUTE-PER-ROW (different orientation).**
  Header row 50 labels three value columns: col1 `BITR`, col2 `MTD`, col3 `YTD`
  (all WS). Col0 is the route name (`TD3 C`, `TD7`, …, `TD22`, `TC*`, `BLPG*`).
  Lists TD1–TD25 and TC/BLPG only — **no `TD28`, no `USG Afra`**. Only the
  **col1 `BITR`** value is ingested (see BITR below); MTD/YTD ignored.
  NOTE: in this table `TD22` BITR is in **raw millions** (e.g. `18791667`) and
  must be ÷1e6 — unlike the top curve table where TD22 is already LSM-scale.

Attachments also include an inline `image.png` (email-signature logo) — ignored.

## Decisions (confirmed)

- **Instruments — explicit keep/rename map** (not a "contains TD" filter).
  Kept columns and their output names:
  | raw header | → instrument | LSM? |
  |---|---|---|
  | `TD3 C` | `TD3C` | |
  | `TD20 inc` | `TD20` | |
  | `TD7` | `TD7` | |
  | `TD8` | `TD8` | |
  | `TD19` | `TD19` | |
  | `TD22` | `TD22` | ✓ |
  | `TD25 inc` | `TD25` | |
  | `TD28` | `TD28` | ✓ |
  | `USG Afra Exc` | `USG Afra Exc` | |
  | `USG AFRA Inc` | `USG Afra Inc` | |
  - **Dropped:** `X-UK Cont P.` (near-duplicate of `TD7`), all `TC*`, all
    `BLPG*`, and the `World Scale` label column.
  - The map lives in a maintainable lookup (see Components) so names/keep-set can
    change without code edits. Any raw header **not** in the map is dropped
    (and logged, so a new josh column is noticed).
- **Units (curve blocks):** keep both, distinguished by `uom`: Block 1 → `WSC`,
  Block 2 → `PMT`.
- **LSM routes — `TD22` and `TD28`:** in the **WS curve block (Block 1)**, label
  these `uom=LSM` (not `WSC`); their Block-2 rows stay `uom=PMT`.
  **Do NOT divide by 1e6 in the curve blocks** — josh already reports them at
  LSM scale (TD22 WS ≈ 20.4, TD28 WS ≈ 2.6; matching existing master LSM ≈ 18.8).
  (The ÷1e6 applies only to the linked-table BITR value — see below.)
- **WSFR flat rates (row 22):** one row per kept instrument with a non-null
  value → `uom='WSFR'`, `periodType='WSFR'`, `period` = first of report month
  (e.g. `2026-08-01`), `value` = the flat rate as-is. (TD22 has no WSFR value →
  skipped; USG Afra WSFR included if present.)
- **BITR (linked table, col1):** for each kept route present in the linked table
  (`TD3C`, `TD7`, `TD8`, `TD19`, `TD20`, `TD22`, `TD25` — `TD28`/`USG Afra`
  absent there), emit `periodType='BITR'`, `period` = first of report month,
  `value` = col1. `uom='WSC'` for all **except `TD22` → `uom='LSM'` with
  value ÷1e6** (raw `18791667` → `18.79`). Route names normalized via the same
  instrument map (`TD3 C`→`TD3C`). MTD/YTD columns ignored.
- **Curve-block tenors → (period date, periodType):** keep months, quarters,
  cals, and Balmo; **drop month-range strips**. (WSFR and BITR rows are dated
  as defined in their bullets above, not here.)
  | tenor | periodType | period (date) | source of date |
  |---|---|---|---|
  | `Balmo` | `BAL` | first of report month | computed (report month, day=1) |
  | month (real date) | `M` | that date | as-is |
  | `Q4-26`… | `Q` | via `lookup/periods.csv` | lookup (format already matches) |
  | `Cal-27/28/29` | `A` | via lookup (`Cal-27`→`CAL27`) | lookup |
  - `BAL` is a **new** periodType — the real balance-of-month the csv/xlsx
    feeds lack.
  - **Strips dropped:** any tenor label matching a month-range span —
    `<Mon>-<Mon>'YY` (e.g. `Aug-Dec'26`, `Jul-Dec`, `Nov-Dec`, `Dec-Dec`) — is
    excluded. No `STRIP` periodType is produced.
- **Publish:** full — shortened `_last/30/60` windows + S3 upload to
  `BROKER/MASTER/`, plus K: copy of `GFI_josh.csv` and `GFI_josh_last.csv`.

## Output schema (`data/GFI_josh.csv`)

Matches the xlsx master's columns:

```
source, periodType, date, instrument, period, uom, value
```

- `source = 'GFI'`, `date` = report date, `value` numeric (rows with
  non-numeric/NaN value dropped).
- **`periodType` vocab:** `M`, `Q`, `A`, `BAL`, `BITR`, `WSFR`.
- **`uom` vocab:** `WSC`, `PMT`, `LSM`, `WSFR`.
- **Dedupe key:** `['periodType','date','instrument','period','uom']` keeping
  the last row. NOTE: `uom` is added to the key vs the other masters, because
  josh carries the same instrument/tenor in multiple units (WSC/LSM, PMT, WSFR).

## Components

New / changed files, following the existing csv/xlsx split:

1. **`utils/read_josh_file.py`** (new) — `main(file)` / `readFile(file)` reading
   `./data/josh/<file>`, returning the long-format DataFrame above. Produces
   three row groups and concatenates them:
   - **curve blocks** — melt Block 1 (`uom=WSC`) and Block 2 (`uom=PMT`);
     resolve tenor→(period,periodType) for BAL/M/Q/A; drop month-range strips;
     apply the instrument keep/rename map; label `TD22`/`TD28` WS rows as `LSM`
     (no division);
   - **WSFR row** (row 22) — `uom=WSFR`, `periodType=WSFR`, period = BOM;
   - **BITR** (linked table col1) — `periodType=BITR`, period = BOM, `uom=WSC`
     except `TD22`→`LSM` ÷1e6; route names via the instrument map.
   Tenor dates for Q/A come from merging `lookup/periods.csv`; BAL/BITR/WSFR use
   the first-of-report-month; months are already real dates. Logs any raw header
   or tenor label it can't map (rather than silently dropping).

2. **`lookup/josh_instruments.csv`** (new) — the instrument keep/rename map:
   columns `header, instrument, lsm` (one row per kept raw header). Single source
   of truth for which columns are kept, their output names, and the LSM flag.
   Editable without code changes.

3. **`utils/outlook_download.py`** (change, backward-compatible) — generalize
   `download_reports()` to accept:
   - `attachment_match(filename) -> bool` (already present), and
   - `date_resolver(message) -> 'YYYY-MM-DD' | None` (new, defaults to the
     current `report_datestr`, i.e. the Braemar-xlsx cell — existing csv/xlsx
     behavior unchanged).
   Josh passes a resolver that saves the `Curves*.xlsx` attachment to a temp
   file and reads `iloc[0,0]`.

4. **`utils/report_date.py`** (change) — add a josh date resolver
   (`josh_report_datestr(message)`): find the `Curves`-prefixed `.xlsx`
   attachment, read its `iloc[0,0]`, validate the bare `YYYY-MM-DD` shape
   (reuse the existing `_DATE_RE` guard). Returns None otherwise.

5. **`utils/downloader_josh.py`** (new) — thin wrapper like `downloader_xlsx.py`:
   calls `download_reports(subfolder='josh', ext='.xlsx',
   attachment_match=<'Curves' prefix + '.xlsx'>, dayStart, since,
   date_resolver=josh_report_datestr)`. Optional secondary guard: sender SMTP
   ends with `@braemar.com`.

6. **`main.py`** (change) — add `joshDownloader(counter, force)` modeled on
   `xlsxDownloader`:
   - cursor key `GFI_josh` (`get_cursor`/`set_cursor`);
   - read master `./data/GFI_josh.csv`, concat parsed new files, dedupe on the
     5-key above, change-aware write (skip write+publish when no new rows unless
     `--force`);
   - `processBroker(df, './data/', 'GFI_josh', './data/master/', 'BROKER/MASTER')`;
   - `copyToKDrive(['./data/GFI_josh.csv', './data/shortened/GFI_josh_last.csv'])`.
   - Called from `main()` in the same `force or runFunctionCheck` block, after
     `xlsxDownloader`. No MTD carry-over (josh-specific logic not needed).

## Download & dating flow

- Reads the **`gfi` Inbox subfolder** — an Outlook rule now files josh's mail
  there, so all three pipelines scan the same folder.
- Pipelines don't collide: csv matches `GFI Bra*`, xlsx matches `Braemar*`,
  josh matches `Curves*.xlsx`. Each pipeline's date resolver returns None for
  the other senders' mail, so non-matching emails are cleanly skipped.
- Files saved as `data/josh/<YYYY-MM-DD>.xlsx`. Amendment/resend handling
  inherited from `download_reports` (subject `correction|amendment` overwrites;
  plain resend of an on-disk date is skipped).

## Run gating & state

- Runs under the existing once-per-day gate (`checkRunCondition()` keyed off the
  csv master) — no change; josh arrives on the same daily cadence.
- New `GFI_josh` high-water-mark in `data/state.json` (self-healing, git-ignored).

## One-time migration

- Rename the 6 files already pulled into `data/josh/`
  (`Curves 100826.xlsx` … `Curves 170826.xlsx`) to `YYYY-MM-DD.xlsx`.
- Build the initial `data/GFI_josh.csv` by parsing those 6 files (this becomes
  the seed master; subsequent runs append incrementally).

## Out of scope / non-goals

- No changes to the csv/xlsx pipelines' output or schemas.
- Linked-table **MTD/YTD** columns not ingested (only its `BITR` col1 is).
- Month-range strip rows (`Aug-Dec'26`, `Jul-Dec`, …) explicitly dropped.
- `TC*`, `BLPG*`, and `X-UK Cont P.` columns not ingested (available in the file
  if scope later expands).
- No backfill before 2026-08-10 (feed started then).

## Risks / watch-items

- **`periodType` proliferation:** `BAL` and `WSFR` are new codes (and `WSFR` is
  both a periodType and a `uom`). Downstream consumers of `GFI_josh.csv` must
  expect them.
- **`Cal`/quarter label drift:** if josh changes label formatting (`Cal-27` vs
  `CAL-27`), the lookup merge silently drops those rows (NaN period). The parser
  should log any tenor label it can't resolve rather than dropping silently —
  distinguishing a deliberately-dropped strip from an unexpected/unmapped label.
