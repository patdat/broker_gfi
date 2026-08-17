# Josh Curves Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third ETL pipeline to `main.py` that ingests Josh Smithson's daily "GFI FFA Curves" email (`Curves DDMMYY.xlsx`), parses it, and publishes a new master `data/GFI_josh.csv`.

**Architecture:** A new deterministic parser (`utils/read_josh_file.py`) melts the Curves file's two stacked curve blocks (World Scale + USD/Tonne) plus its WSFR flat-rate row and `Linked`-table BITR values into the house long format. A thin downloader wrapper reuses a generalized `download_reports()` loop (now accepting a per-pipeline `date_resolver`). `main.py` gains a `joshDownloader()` compiler modeled on the existing `xlsxDownloader()`, sharing the cursor/change-detection/publish machinery.

**Tech Stack:** Python 3.13, pandas, numpy, openpyxl, pywin32 (Outlook), boto3. No test framework in the repo — tests are standalone assertion scripts run with the venv Python against the real sample files already in `data/josh/`.

## Global Constraints

- **Windows-only, run from repo root.** All paths are relative (`./data`, `./lookup`). Tests and scripts must be invoked from `C:\repo\broker_gfi`.
- **Interpreter:** `./.venv/Scripts/python.exe` (never bare `python`).
- **Output schema (exact column order):** `source, periodType, date, instrument, period, uom, value`.
- **`source` is always `'GFI'`.**
- **Dedupe key:** `['periodType','date','instrument','period','uom']`, keeping the last row.
- **`periodType` vocab:** `M, Q, A, BAL, BITR, WSFR`. **`uom` vocab:** `WSC, PMT, LSM, WSFR`.
- **Cloud/K: failures are non-fatal** (logged, pipeline continues) — never let them raise.
- **Do not `git add -A`** — window CSVs churn cosmetically; add only files a task actually changed.
- Commit messages end with the repo's `Co-Authored-By` trailer.

---

## File Structure

- `lookup/josh_instruments.csv` (new) — instrument keep/rename map: `header,instrument,lsm`.
- `utils/read_josh_file.py` (new) — the Curves parser. `main(file) -> DataFrame`.
- `utils/report_date.py` (modify) — add `read_curves_date`, `resolve_curves_date`, `josh_report_datestr`.
- `utils/outlook_download.py` (modify) — add `date_resolver` param to `download_reports` (default = existing behavior).
- `utils/downloader_josh.py` (new) — thin wrapper, `main(dayStart, since=None) -> (new_files, latest_seen)`.
- `main.py` (modify) — add `joshDownloader(counter, force)`, call it from `main()`; add seed-master bootstrap.
- `data/josh/*.xlsx` (rename) — the 6 already-pulled files → `YYYY-MM-DD.xlsx`.
- `tests/` (new) — standalone assertion scripts.

---

## Task 1: Rename pulled sample files to `YYYY-MM-DD.xlsx`

Gives every later task stable fixture filenames. The 6 files currently in `data/josh/` are named `Curves DDMMYY.xlsx`; rename each to its internal report date (`iloc[0,0]`), matching how the production downloader will name them.

**Files:**
- Modify (rename): `data/josh/Curves *.xlsx` → `data/josh/YYYY-MM-DD.xlsx`
- Create: `scripts/rename_josh_files.py` (one-shot migration helper, kept for reference)

**Interfaces:**
- Produces: renamed fixtures `data/josh/2026-08-10.xlsx`, `2026-08-11.xlsx`, `2026-08-12.xlsx`, `2026-08-13.xlsx`, `2026-08-14.xlsx`, `2026-08-17.xlsx`.

- [ ] **Step 1: Write the migration script**

Create `scripts/rename_josh_files.py`:

```python
"""One-shot: rename data/josh/Curves*.xlsx to <internal-date>.xlsx.

The internal date is the file's own cell iloc[0,0] (the report date), the same
value the production downloader names files by. Idempotent: files already named
YYYY-MM-DD.xlsx are skipped."""

import os
import glob
import re
import warnings
import pandas as pd

JOSH_DIR = './data/josh'
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def main():
    for path in sorted(glob.glob(os.path.join(JOSH_DIR, '*.xlsx'))):
        base = os.path.splitext(os.path.basename(path))[0]
        if _DATE_RE.match(base):
            print(f'skip (already dated): {base}.xlsx')
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            df = pd.read_excel(path, header=None)
        datestr = pd.to_datetime(df.iloc[0, 0]).strftime('%Y-%m-%d')
        assert _DATE_RE.match(datestr), f'bad date {datestr!r} from {path}'
        dest = os.path.join(JOSH_DIR, f'{datestr}.xlsx')
        os.rename(path, dest)
        print(f'renamed: {os.path.basename(path)} -> {datestr}.xlsx')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Run the migration**

Run: `./.venv/Scripts/python.exe scripts/rename_josh_files.py`
Expected: 6 `renamed:` lines (`Curves 100826.xlsx -> 2026-08-10.xlsx`, etc.).

- [ ] **Step 3: Verify the fixtures exist**

Run:
```bash
./.venv/Scripts/python.exe -c "import glob; print(sorted(x.split('/')[-1] for x in glob.glob('data/josh/*.xlsx')))"
```
Expected: `['2026-08-10.xlsx', '2026-08-11.xlsx', '2026-08-12.xlsx', '2026-08-13.xlsx', '2026-08-14.xlsx', '2026-08-17.xlsx']`

- [ ] **Step 4: Commit**

```bash
git add scripts/rename_josh_files.py
git add -A data/josh
git commit -m "Rename josh Curves samples to internal-date filenames"
```

---

## Task 2: Instrument map + tenor resolver + curve-block parser

Build the parser core: the keep/rename lookup, the tenor→(period,periodType) resolver, and melting of the two curve blocks (WSC + PMT), with strips dropped and TD22/TD28 labeled LSM in the WS block.

**Files:**
- Create: `lookup/josh_instruments.csv`
- Create: `utils/read_josh_file.py`
- Create: `tests/test_read_josh_curves.py`

**Interfaces:**
- Consumes: renamed fixture `data/josh/2026-08-17.xlsx` (Task 1); `lookup/periods.csv` (existing: columns `period,plmName,periodicity`).
- Produces:
  - `utils/read_josh_file.py::main(file: str) -> pd.DataFrame` with columns `source, periodType, date, instrument, period, uom, value`.
  - Internal helpers other tasks extend in the SAME file: `load_instrument_map(path=...) -> dict[str, tuple[str, bool]]` (header → (instrument, lsm)), `load_periods(path=...) -> dict[str, tuple[pd.Timestamp, str]]`, `resolve_tenor(label, report_date, periods) -> tuple[pd.Timestamp, str] | None`, `_parse_block(df, r0, r1, imap, periods, report_date, block_uom) -> list[tuple]`.

- [ ] **Step 1: Create the instrument map lookup**

Create `lookup/josh_instruments.csv` (exact contents):

```csv
header,instrument,lsm
TD3 C,TD3C,
TD20 inc,TD20,
TD7,TD7,
TD8,TD8,
TD19,TD19,
TD22,TD22,True
TD25 inc,TD25,
TD28,TD28,True
USG Afra Exc,USG Afra Exc,
USG AFRA Inc,USG Afra Inc,
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_read_josh_curves.py`:

```python
"""Curve-block assertions for read_josh_file, against data/josh/2026-08-17.xlsx.
Run from repo root with the venv python."""

import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_josh_file

FILE = '2026-08-17.xlsx'


def _val(df, instrument, periodType, uom, period):
    m = df[(df.instrument == instrument) & (df.periodType == periodType)
           & (df.uom == uom) & (df.period == pd.Timestamp(period))]
    assert len(m) == 1, f'expected 1 row, got {len(m)} for {instrument}/{periodType}/{uom}/{period}'
    return float(m.iloc[0].value)


def test_curve_values():
    df = read_josh_file.main(FILE)

    # schema + source/date
    assert list(df.columns) == ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']
    assert (df['source'] == 'GFI').all()
    assert (df['date'] == pd.Timestamp('2026-08-17')).all()

    # WSC front-month + Balmo + PMT
    assert _val(df, 'TD3C', 'M', 'WSC', '2026-08-01') == 470
    assert abs(_val(df, 'TD3C', 'BAL', 'WSC', '2026-08-01') - 470.18555555555554) < 1e-6
    assert abs(_val(df, 'TD3C', 'M', 'PMT', '2026-08-01') - 94.987) < 1e-3

    # LSM routes in the WS block (no division)
    assert _val(df, 'TD22', 'M', 'LSM', '2026-08-01') == 19.5
    assert abs(_val(df, 'TD28', 'BAL', 'LSM', '2026-08-01') - 2.637037222222222) < 1e-6

    # quarter + cal tenor resolution
    assert _val(df, 'TD3C', 'Q', 'WSC', '2026-10-01') == 440
    assert abs(_val(df, 'TD3C', 'A', 'WSC', '2027-01-01') - 275.85353785254824) < 1e-6

    # USG Afra kept, verbatim-ish names
    assert _val(df, 'USG Afra Exc', 'M', 'WSC', '2026-08-01') == 345.46
    assert _val(df, 'USG Afra Inc', 'M', 'WSC', '2026-08-01') == 360

    # dropped: TC*, BLPG*, X-UK Cont P.
    assert df[df.instrument.str.startswith('TC')].empty
    assert df[df.instrument.str.startswith('BLPG')].empty
    assert df[df.instrument.str.contains('UK')].empty

    # strip dropped: TD3C WSC has exactly BAL(1)+months(8)+quarters(7)+cals(3)=19 rows
    assert len(df[(df.instrument == 'TD3C') & (df.uom == 'WSC')]) == 19

    print('test_curve_values OK')


if __name__ == '__main__':
    test_curve_values()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe tests/test_read_josh_curves.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.read_josh_file'` (module not created yet).

- [ ] **Step 4: Write the curve-block parser**

Create `utils/read_josh_file.py`:

```python
"""Parse Josh Smithson's 'GFI FFA Curves' xlsx into the house long format.

The Curves file (see docs) stacks a World Scale curve block and a USD/Tonne
curve block (instruments across columns, tenors down rows), plus a WSFR
flat-rate row and a `Linked` BITR table. This module melts the parts we keep
into: source, periodType, date, instrument, period, uom, value.

Nothing here touches Outlook; it operates on a file already in ./data/josh."""

import os
import re
import warnings
import numpy as np
import pandas as pd

warnings.simplefilter('ignore')

JOSH_DIR = './data/josh'
_INSTRUMENT_MAP_PATH = './lookup/josh_instruments.csv'
_PERIODS_PATH = './lookup/periods.csv'

# curve blocks: (first_row, last_row) inclusive, and their default uom
_WSC_BLOCK = (1, 20)
_PMT_BLOCK = (25, 44)

# month-range strip labels to DROP, e.g. "Aug-Dec'26", "Jul-Dec", "Dec-Dec"
_STRIP_RE = re.compile(r"^[A-Za-z]{3}-[A-Za-z]{3}")
# annual cal label, e.g. "Cal-27" / "Cal27" -> lookup code "CAL27"
_CAL_RE = re.compile(r"^cal-?(\d{2})$", re.IGNORECASE)


def load_instrument_map(path=_INSTRUMENT_MAP_PATH):
    """header (raw column label) -> (output instrument, lsm_flag)."""
    m = pd.read_csv(path)
    out = {}
    for _, row in m.iterrows():
        lsm = str(row['lsm']).strip().lower() == 'true'
        out[str(row['header']).strip()] = (str(row['instrument']).strip(), lsm)
    return out


def load_periods(path=_PERIODS_PATH):
    """period code (upper) -> (plmName Timestamp, periodicity upper)."""
    lk = pd.read_csv(path)
    out = {}
    for _, r in lk.iterrows():
        code = str(r['period']).strip().upper()
        plm = pd.to_datetime(r['plmName']) if not pd.isna(r['plmName']) else pd.NaT
        out[code] = (plm, str(r['periodicity']).strip().upper())
    return out


def resolve_tenor(label, report_date, periods):
    """Map a tenor label to (period Timestamp, periodType), or None to drop.

    - real datetime  -> ('M', that date)
    - 'Balmo'        -> ('BAL', first of report month)
    - 'Aug-Dec'26'   -> None (month-range strip, dropped)
    - 'Cal-27'       -> ('A', via periods lookup on 'CAL27')
    - 'Q4-26' etc.   -> (periodicity, via periods lookup)
    - anything else  -> None (caller logs)
    """
    if not isinstance(label, str) and hasattr(label, 'year'):  # real date cell -> month
        return (pd.Timestamp(label), 'M')
    s = str(label).strip()
    if s.lower() == 'balmo':
        return (pd.Timestamp(report_date).replace(day=1), 'BAL')
    if _STRIP_RE.match(s):
        return None
    cal = _CAL_RE.match(s)
    if cal:
        hit = periods.get('CAL' + cal.group(1))
        return (hit[0], 'A') if hit is not None else None
    hit = periods.get(s.upper())
    return (hit[0], hit[1]) if hit is not None else None


def _parse_block(df, r0, r1, imap, periods, report_date, block_uom):
    """Melt one curve block into rows: (instrument, period, periodType, uom, value)."""
    header = df.iloc[0]
    rows = []
    for c in range(1, df.shape[1]):
        raw = str(header[c]).strip()
        if raw not in imap:
            continue
        instrument, lsm = imap[raw]
        for r in range(r0, r1 + 1):
            resolved = resolve_tenor(df.iloc[r, 0], report_date, periods)
            if resolved is None:
                continue
            period, ptype = resolved
            uom = 'LSM' if (block_uom == 'WSC' and lsm) else block_uom
            rows.append((instrument, period, ptype, uom, df.iloc[r, c]))
    return rows


def _assemble(rows, report_date):
    """Rows -> cleaned, deduped, schema-ordered DataFrame."""
    out = pd.DataFrame(rows, columns=['instrument', 'period', 'periodType', 'uom', 'value'])
    out['value'] = pd.to_numeric(out['value'], errors='coerce')
    out = out.dropna(subset=['value'])
    out['period'] = pd.to_datetime(out['period'])
    out['source'] = 'GFI'
    out['date'] = pd.Timestamp(report_date)
    out = out[['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']]
    out = out.drop_duplicates(
        subset=['periodType', 'date', 'instrument', 'period', 'uom'], keep='last')
    return out.reset_index(drop=True)


def readFile(file):
    path = os.path.join(JOSH_DIR, file)
    df = pd.read_excel(path, header=None)
    report_date = pd.to_datetime(df.iloc[0, 0])
    imap = load_instrument_map()
    periods = load_periods()

    rows = []
    rows += _parse_block(df, *_WSC_BLOCK, imap, periods, report_date, 'WSC')
    rows += _parse_block(df, *_PMT_BLOCK, imap, periods, report_date, 'PMT')
    return _assemble(rows, report_date)


def main(file):
    return readFile(file)


if __name__ == '__main__':
    print(main('2026-08-17.xlsx'))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe tests/test_read_josh_curves.py`
Expected: `test_curve_values OK`

- [ ] **Step 6: Commit**

```bash
git add lookup/josh_instruments.csv utils/read_josh_file.py tests/test_read_josh_curves.py
git commit -m "Add josh Curves parser: instrument map + curve blocks (WSC/PMT)"
```

---

## Task 3: Add WSFR flat-rate + BITR (Linked table) rows

Extend the parser with the WSFR row (row 22) and the `Linked` table's BITR column, including the TD22 ÷1e6 correction unique to that table.

**Files:**
- Modify: `utils/read_josh_file.py`
- Create: `tests/test_read_josh_wsfr_bitr.py`

**Interfaces:**
- Consumes: helpers from Task 2 in the same file (`load_instrument_map`, `_assemble`).
- Produces: `_parse_wsfr(df, imap, report_date) -> list[tuple]`, `_parse_bitr(df, keepset_lsm, report_date) -> list[tuple]`; `readFile` now returns curve + WSFR + BITR rows.

- [ ] **Step 1: Write the failing test**

Create `tests/test_read_josh_wsfr_bitr.py`:

```python
import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_josh_file

FILE = '2026-08-17.xlsx'


def _val(df, instrument, periodType, uom, period):
    m = df[(df.instrument == instrument) & (df.periodType == periodType)
           & (df.uom == uom) & (df.period == pd.Timestamp(period))]
    assert len(m) == 1, f'expected 1 row, got {len(m)} for {instrument}/{periodType}/{uom}/{period}'
    return float(m.iloc[0].value)


def test_wsfr_and_bitr():
    df = read_josh_file.main(FILE)

    # WSFR: one row per instrument, period = first of report month
    assert _val(df, 'TD3C', 'WSFR', 'WSFR', '2026-08-01') == 20.21
    assert _val(df, 'USG Afra Exc', 'WSFR', 'WSFR', '2026-08-01') == 21.01
    # TD22 has no WSFR value -> no row
    assert df[(df.instrument == 'TD22') & (df.periodType == 'WSFR')].empty

    # BITR from the Linked table, period = first of report month
    assert _val(df, 'TD3C', 'BITR', 'WSC', '2026-08-01') == 501.67
    assert _val(df, 'TD25', 'BITR', 'WSC', '2026-08-01') == 377.22
    # TD22 BITR is in raw millions in the Linked table -> /1e6, uom LSM
    assert abs(_val(df, 'TD22', 'BITR', 'LSM', '2026-08-01') - 18.791667) < 1e-6

    # TD28 and USG Afra are not in the Linked table -> no BITR rows
    assert df[(df.instrument == 'TD28') & (df.periodType == 'BITR')].empty
    assert df[(df.instrument.str.contains('USG')) & (df.periodType == 'BITR')].empty

    print('test_wsfr_and_bitr OK')


if __name__ == '__main__':
    test_wsfr_and_bitr()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe tests/test_read_josh_wsfr_bitr.py`
Expected: FAIL — assertion error (`expected 1 row, got 0`) because WSFR/BITR rows aren't produced yet.

- [ ] **Step 3: Add the WSFR and BITR parsers**

In `utils/read_josh_file.py`, add these two functions after `_parse_block`:

```python
_WSFR_ROW = 22  # flat-rate row, one value per instrument column


def _parse_wsfr(df, imap, report_date):
    """WSFR flat rates (row 22): one row per kept instrument with a value.

    period = first of report month; periodType = uom = 'WSFR'."""
    header = df.iloc[0]
    period = pd.Timestamp(report_date).replace(day=1)
    rows = []
    for c in range(1, df.shape[1]):
        raw = str(header[c]).strip()
        if raw not in imap:
            continue
        instrument, _ = imap[raw]
        val = df.iloc[_WSFR_ROW, c]
        if pd.isna(val):
            continue
        rows.append((instrument, period, 'WSFR', 'WSFR', val))
    return rows


def _parse_bitr(df, keepset_lsm, report_date):
    """BITR from the `Linked` table (col 1), routes down the rows.

    keepset_lsm maps a space-stripped instrument name -> lsm_flag. Matches the
    linked route names (which use e.g. 'TD3 C', 'TD20', 'TD25' — different from
    the curve headers). TD22's BITR is in raw millions there, so /1e6 + uom LSM;
    all others are uom WSC. period = first of report month."""
    period = pd.Timestamp(report_date).replace(day=1)
    rows = []
    for r in range(df.shape[0]):
        name = df.iloc[r, 0]
        if not isinstance(name, str):
            continue
        canon = name.replace(' ', '').strip()
        if canon not in keepset_lsm:
            continue
        val = df.iloc[r, 1]
        if pd.isna(val):
            continue
        if keepset_lsm[canon]:
            uom, val = 'LSM', val / 1e6
        else:
            uom = 'WSC'
        rows.append((canon, period, 'BITR', uom, val))
    return rows
```

Then update `readFile` to include them (add the two lines before `return`):

```python
def readFile(file):
    path = os.path.join(JOSH_DIR, file)
    df = pd.read_excel(path, header=None)
    report_date = pd.to_datetime(df.iloc[0, 0])
    imap = load_instrument_map()
    periods = load_periods()
    keepset_lsm = {inst.replace(' ', ''): lsm for (inst, lsm) in imap.values()}

    rows = []
    rows += _parse_block(df, *_WSC_BLOCK, imap, periods, report_date, 'WSC')
    rows += _parse_block(df, *_PMT_BLOCK, imap, periods, report_date, 'PMT')
    rows += _parse_wsfr(df, imap, report_date)
    rows += _parse_bitr(df, keepset_lsm, report_date)
    return _assemble(rows, report_date)
```

- [ ] **Step 4: Run both parser tests to verify they pass**

Run:
```bash
./.venv/Scripts/python.exe tests/test_read_josh_wsfr_bitr.py && ./.venv/Scripts/python.exe tests/test_read_josh_curves.py
```
Expected: `test_wsfr_and_bitr OK` then `test_curve_values OK`.

Note: `test_curve_values` still asserts `len(TD3C, WSC) == 19` — but TD3C now also has a BITR/WSC row at `2026-08-01`, making 20. **Update that assertion in `tests/test_read_josh_curves.py`** from `== 19` to `== 20`, and adjust its comment to `+ BITR(1)`. Re-run to confirm both pass.

- [ ] **Step 5: Commit**

```bash
git add utils/read_josh_file.py tests/test_read_josh_wsfr_bitr.py tests/test_read_josh_curves.py
git commit -m "Add josh Curves WSFR + Linked-table BITR parsing"
```

---

## Task 4: Validate the parser across all 6 sample files

A reviewer gate confirming the parser handles every real file (not just 2026-08-17) with no crashes and only in-vocab values.

**Files:**
- Create: `tests/test_read_josh_allfiles.py`

**Interfaces:**
- Consumes: `read_josh_file.main`; all 6 renamed fixtures.

- [ ] **Step 1: Write the test**

Create `tests/test_read_josh_allfiles.py`:

```python
import os
import sys
import glob
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_josh_file

PERIODTYPES = {'M', 'Q', 'A', 'BAL', 'BITR', 'WSFR'}
UOMS = {'WSC', 'PMT', 'LSM', 'WSFR'}
KEEP = {'TD3C', 'TD20', 'TD7', 'TD8', 'TD19', 'TD22', 'TD25', 'TD28',
        'USG Afra Exc', 'USG Afra Inc'}
SCHEMA = ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']


def test_all_files():
    files = sorted(os.path.basename(p) for p in glob.glob('data/josh/*.xlsx'))
    assert len(files) == 6, f'expected 6 fixtures, found {files}'
    for f in files:
        df = read_josh_file.main(f)
        assert list(df.columns) == SCHEMA, f'{f}: bad schema {list(df.columns)}'
        assert len(df) > 0, f'{f}: no rows'
        assert set(df.periodType) <= PERIODTYPES, f'{f}: bad periodTypes {set(df.periodType)}'
        assert set(df.uom) <= UOMS, f'{f}: bad uoms {set(df.uom)}'
        assert set(df.instrument) <= KEEP, f'{f}: unexpected instruments {set(df.instrument) - KEEP}'
        assert df.value.notna().all(), f'{f}: null values present'
        # date column equals the file's date name
        assert (df.date == pd.Timestamp(f[:-5])).all(), f'{f}: date mismatch'
        print(f'{f}: {len(df)} rows OK')
    print('test_all_files OK')


if __name__ == '__main__':
    test_all_files()
```

- [ ] **Step 2: Run the test**

Run: `./.venv/Scripts/python.exe tests/test_read_josh_allfiles.py`
Expected: 6 `<date>.xlsx: N rows OK` lines, then `test_all_files OK`. If any file logs an unmapped tenor/header warning or fails a set assertion, inspect that file before proceeding — a new label may need a periods.csv or instrument-map entry.

- [ ] **Step 3: Commit**

```bash
git add tests/test_read_josh_allfiles.py
git commit -m "Add cross-file validation for josh Curves parser"
```

---

## Task 5: Josh date resolver + generalized downloader

Add Outlook-side wiring: a date resolver that reads the Curves file's `iloc[0,0]`, a backward-compatible `date_resolver` hook on the shared download loop, and the josh downloader wrapper.

**Files:**
- Modify: `utils/report_date.py`
- Modify: `utils/outlook_download.py`
- Create: `utils/downloader_josh.py`
- Create: `tests/test_curves_date.py`

**Interfaces:**
- Consumes: `download_reports` (existing); fixture `data/josh/2026-08-17.xlsx`.
- Produces:
  - `report_date.py::read_curves_date(path) -> pd.Timestamp | None`, `resolve_curves_date(message)`, `josh_report_datestr(message) -> str | None`.
  - `outlook_download.py::download_reports(subfolder, ext, attachment_match, dayStart, since=None, date_resolver=None)` — `date_resolver=None` keeps the existing Braemar behavior.
  - `downloader_josh.py::main(dayStart, since=None) -> (new_files, latest_seen)`.

- [ ] **Step 1: Write the failing test (pure date-cell read, no Outlook)**

Create `tests/test_curves_date.py`:

```python
import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import report_date

def test_read_curves_date():
    ts = report_date.read_curves_date('data/josh/2026-08-17.xlsx')
    assert ts == pd.Timestamp('2026-08-17'), ts
    print('test_read_curves_date OK')

if __name__ == '__main__':
    test_read_curves_date()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe tests/test_curves_date.py`
Expected: FAIL — `AttributeError: module 'utils.report_date' has no attribute 'read_curves_date'`.

- [ ] **Step 3: Add the josh date resolver to `report_date.py`**

Append to `utils/report_date.py` (it already imports `os`, `re`, `tempfile`, `warnings`, `pd`, and defines `_DATE_RE`, `_XLSX_SUFFIX`):

```python
_CURVES_PREFIX = 'Curves'


def read_curves_date(path):
    """The report date from a Josh Curves xlsx (cell iloc[0,0]).

    Returns a pandas.Timestamp, or None if the file/cell can't be parsed."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            df = pd.read_excel(path, header=None)
        return pd.to_datetime(df.iloc[0, 0])
    except Exception:
        return None


def _curves_attachment(message):
    for attachment in message.Attachments:
        name = attachment.FileName
        if name.startswith(_CURVES_PREFIX) and name.endswith(_XLSX_SUFFIX):
            return attachment
    return None


def resolve_curves_date(message):
    """Read the report date from the message's `Curves*.xlsx` attachment."""
    attachment = _curves_attachment(message)
    if attachment is None:
        return None
    fd, tmp = tempfile.mkstemp(suffix='.xlsx', prefix='josh_probe_')
    os.close(fd)
    try:
        attachment.SaveAsFile(tmp)
        return read_curves_date(tmp)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def josh_report_datestr(message):
    """Resolve the josh report date as a validated `YYYY-MM-DD` string, or None.

    None means: no Curves attachment, or an unparseable/badly-shaped date.
    Callers MUST treat None as 'save nothing'."""
    date = resolve_curves_date(message)
    if date is None:
        return None
    datestr = date.strftime('%Y-%m-%d')
    if not _DATE_RE.match(datestr):
        return None
    return datestr
```

- [ ] **Step 4: Run the date test to verify it passes**

Run: `./.venv/Scripts/python.exe tests/test_curves_date.py`
Expected: `test_read_curves_date OK`

- [ ] **Step 5: Generalize `download_reports` with a `date_resolver` hook**

In `utils/outlook_download.py`, change the signature and the one line that resolves the date. The import `from utils.report_date import report_datestr, is_amendment` already exists.

Change the signature:
```python
def download_reports(subfolder, ext, attachment_match, dayStart, since=None, date_resolver=None):
```

Immediately inside the function (before the `try:`), add the default:
```python
    if date_resolver is None:
        date_resolver = report_datestr  # existing Braemar-xlsx behavior
```

Change the resolve line from:
```python
            datestr = report_datestr(message)
```
to:
```python
            datestr = date_resolver(message)
```

(Existing `downloader_csv`/`downloader_xlsx` call `download_reports` without `date_resolver`, so they keep the default — no behavior change.)

- [ ] **Step 6: Create the josh downloader wrapper**

Create `utils/downloader_josh.py`:

```python
"""Download Josh Smithson's 'GFI FFA Curves' xlsx from the `gfi` Outlook folder.

Josh's mail is filed into the same `gfi` subfolder (Outlook rule). His report
date lives in the Curves file's own cell iloc[0,0], so this pipeline passes a
josh-specific date_resolver. Files are saved to ./data/josh/<internal-date>.xlsx."""

from utils.outlook_download import download_reports
from utils.report_date import josh_report_datestr


def _is_curves_attachment(filename):
    return filename.startswith('Curves') and filename.endswith('.xlsx')


def downloader(dayStart, since=None):
    return download_reports('josh', '.xlsx', _is_curves_attachment, dayStart, since,
                            date_resolver=josh_report_datestr)


def main(dayStart, since=None):
    return downloader(dayStart, since)


if __name__ == '__main__':
    main(3)
```

- [ ] **Step 7: Smoke-test imports (default path unchanged, josh wrapper importable)**

Run:
```bash
./.venv/Scripts/python.exe -c "import utils.downloader_csv, utils.downloader_xlsx, utils.downloader_josh, inspect; from utils.outlook_download import download_reports; p=inspect.signature(download_reports).parameters; assert 'date_resolver' in p and p['date_resolver'].default is None; print('imports + signature OK')"
```
Expected: `imports + signature OK`

- [ ] **Step 8: Commit**

```bash
git add utils/report_date.py utils/outlook_download.py utils/downloader_josh.py tests/test_curves_date.py
git commit -m "Add josh date resolver and date_resolver hook on download loop"
```

---

## Task 6: Wire `joshDownloader` into `main.py` + seed the master

Add the compiler that appends new josh files to `data/GFI_josh.csv` (change-aware, cursor-driven), publishes it, and copies to K:. Bootstrap the initial master from the 6 fixtures.

**Files:**
- Modify: `main.py`
- Create: `data/GFI_josh.csv` (seeded)
- Create: `tests/test_josh_compiler.py`

**Interfaces:**
- Consumes: `read_josh_file.main`, `downloader_josh.main`, `get_cursor`/`set_cursor`, `processBroker`, `copyToKDrive`.
- Produces: `main.py::joshDownloader(counter, force=False) -> pd.DataFrame | None`; `main.py::seedJoshMaster() -> pd.DataFrame` (bootstrap helper).

- [ ] **Step 1: Add imports and the compiler to `main.py`**

In `utils` import block near the top of `main.py`, add:
```python
from utils.downloader_josh import main as downloader_josh
from utils.read_josh_file import main as read_josh_file
```

Add these two functions after `xlsxDownloader` (before `def main(`):

```python
def seedJoshMaster():
    """Build data/GFI_josh.csv from every file currently in ./data/josh.

    One-time bootstrap: parses all fixtures, dedupes, writes the master. Safe to
    re-run (idempotent — dedupe on the 5-key keeps the last row)."""
    files = sorted(f for f in os.listdir('./data/josh') if f.endswith('.xlsx'))
    parts = [read_josh_file(f) for f in files]
    df = pd.concat(parts) if parts else pd.DataFrame(
        columns=['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value'])
    df = df.drop_duplicates(
        subset=['periodType', 'date', 'instrument', 'period', 'uom'], keep='last')
    df.to_csv('./data/GFI_josh.csv', index=False)
    print(f'JOSH: seeded master from {len(files)} file(s): {len(df)} rows')
    return df


def joshDownloader(counter, force=False):
    since = None if force else get_cursor('GFI_josh')
    newFiles, latest = downloader_josh(counter, since)
    if latest is not None:
        set_cursor('GFI_josh', latest)

    newFiles = sorted(newFiles)
    masterFile = pd.read_csv('./data/GFI_josh.csv', parse_dates=['date', 'period'])
    rowsBefore = len(masterFile)

    parts = [masterFile]
    if newFiles:
        print(f'JOSH: {len(newFiles)} new file(s): {newFiles}')
        for file in newFiles:
            parts.append(read_josh_file(file))
    else:
        print('JOSH: no new reports')

    df = pd.concat(parts)
    df = df.drop_duplicates(
        subset=['periodType', 'date', 'instrument', 'period', 'uom'], keep='last')
    newRows = len(df) > rowsBefore

    if not newRows and not force:
        print('JOSH: nothing new - skipping upload')
        return None

    if newRows:
        df.to_csv('./data/GFI_josh.csv', index=False)
    else:
        print('JOSH: [FORCED] no new rows - re-publishing existing master')
    processBroker(df, './data/', 'GFI_josh', './data/master/', 'BROKER/MASTER')
    copyToKDrive(['./data/GFI_josh.csv', './data/shortened/GFI_josh_last.csv'])
    return df
```

- [ ] **Step 2: Call `joshDownloader` from `main()`**

In `main.py::main`, add the josh call in the same gated block, after `xlsxDownloader`:

```python
def main(counter, force=False):
    print(f'Run condition (today > latest date in master): {runFunctionCheck}{" [FORCED]" if force else ""}')
    if force or runFunctionCheck == True:
        csvCompiler(counter, force)
        xlsxDownloader(counter, force)
        joshDownloader(counter, force)
    else:
        print('Master already up to date for today - nothing to do. (use --force to override)')
```

- [ ] **Step 3: Seed the initial master**

Run:
```bash
./.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); import main; main.seedJoshMaster()"
```
Expected: `JOSH: seeded master from 6 file(s): N rows` and a new `data/GFI_josh.csv`.

Note: importing `main` executes `checkRunCondition()` at module load (reads `data/GFI_csvs.csv`) — that's expected and harmless.

- [ ] **Step 4: Write the compiler test**

Create `tests/test_josh_compiler.py`:

```python
import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())


def test_seed_and_schema():
    import main
    df = main.seedJoshMaster()
    assert list(df.columns) == ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']
    assert len(df) > 0
    # master round-trips from disk with the same row count
    on_disk = pd.read_csv('./data/GFI_josh.csv', parse_dates=['date', 'period'])
    assert len(on_disk) == len(df)
    # all 6 report dates present
    assert on_disk['date'].dt.strftime('%Y-%m-%d').nunique() == 6
    # no dupes on the 5-key
    key = ['periodType', 'date', 'instrument', 'period', 'uom']
    assert not on_disk.duplicated(subset=key).any()
    print(f'test_seed_and_schema OK ({len(df)} rows)')


if __name__ == '__main__':
    test_seed_and_schema()
```

- [ ] **Step 5: Run the compiler test**

Run: `./.venv/Scripts/python.exe tests/test_josh_compiler.py`
Expected: `test_seed_and_schema OK (N rows)`

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_josh_compiler.py data/GFI_josh.csv
git commit -m "Wire joshDownloader into main.py and seed GFI_josh.csv"
```

---

## Task 7: End-to-end dry run + docs

Confirm the whole `main.py --force` path runs (Outlook may find nothing new — that's fine) and record the new pipeline in `CLAUDE.md`.

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none (integration verification + docs).

- [ ] **Step 1: Run the full pipeline forced**

Run: `./.venv/Scripts/python.exe main.py --force --days 10`
Expected: the run reaches `JOSH:` log lines and completes with `=== run completed successfully ===`. Cloud/K: lines may show skips (no `.env` / no K:) — that's non-fatal by design. If Outlook is signed in, josh files ≥ 2026-08-10 are (re)confirmed on disk; the master re-publishes under `--force`.

- [ ] **Step 2: Verify the published window files exist**

Run:
```bash
./.venv/Scripts/python.exe -c "import glob; print(sorted(x.split('/')[-1] for x in glob.glob('data/shortened/GFI_josh*.csv')))"
```
Expected: `['GFI_josh_30.csv', 'GFI_josh_60.csv', 'GFI_josh_last.csv']`

- [ ] **Step 3: Document the pipeline in `CLAUDE.md`**

Add a short subsection to `CLAUDE.md` describing the third pipeline: source (`josh.smithson@braemar.com`, `Curves*.xlsx` in the `gfi` subfolder), date from `iloc[0,0]`, output `GFI_josh.csv` with schema `source,periodType,date,instrument,period,uom,value`, the new `BAL`/`WSFR` periodTypes and `LSM`/`WSFR` uoms, TD-only keep-set + USG Afra, and the TD22 ÷1e6-in-BITR-only quirk. Mirror the existing doc's tone. Keep it to a compact paragraph or two under Architecture.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Document josh Curves pipeline in CLAUDE.md"
```

---

## Self-Review Notes

- **Spec coverage:** instrument map (T2), curve blocks WSC/PMT + LSM labeling + strip drop + tenor resolution (T2), WSFR (T3), BITR incl. TD22 ÷1e6 (T3), schema/dedupe (T2 `_assemble`, T6 compiler), download from `gfi` via Curves match + `iloc[0,0]` dating (T5), cursor `GFI_josh` + change-aware compile (T6), full publish incl. K: (T6), rename migration + seed (T1, T6), CLAUDE.md (T7). All spec sections map to a task.
- **Known interaction:** Task 3 changes the TD3C/WSC row count from 19→20 (BITR adds one); Task 3 Step 4 explicitly updates the Task 2 assertion. Flagged to avoid a false failure.
- **Outlook/S3/K: are un-unit-testable** in CI; Tasks 5–7 use import/signature smoke tests and a real `--force` run for integration coverage. This is called out, not hidden.
