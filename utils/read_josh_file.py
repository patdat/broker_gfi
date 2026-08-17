"""Parse Josh Smithson's 'GFI FFA Curves' xlsx into the house long format.

The Curves file (see docs) stacks a World Scale curve block and a USD/Tonne
curve block (instruments across columns, tenors down rows), plus a WSFR
flat-rate row and a `Linked` BITR table. This module melts the parts we keep
into: source, periodType, date, instrument, period, uom, value.

Nothing here touches Outlook; it operates on a file already in ./data/josh."""

import os
import re
import warnings
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


def _parse_block(df, r0, r1, imap, periods, report_date, block_uom, unmapped=None):
    """Melt one curve block into rows: (instrument, period, periodType, uom, value).

    `unmapped`, if given, is a shared set collecting tenor labels (row 0 of each
    block row) that resolve_tenor() dropped but that are NOT a recognized strip
    and NOT blank/NaN -- i.e. genuinely unrecognized, possibly format drift."""
    header = df.iloc[0]
    rows = []
    for c in range(1, df.shape[1]):
        raw = str(header[c]).strip()
        if raw not in imap:
            continue
        instrument, lsm = imap[raw]
        for r in range(r0, r1 + 1):
            label = df.iloc[r, 0]
            resolved = resolve_tenor(label, report_date, periods)
            if resolved is None:
                if unmapped is not None and not pd.isna(label):
                    s = str(label).strip()
                    if s and not _STRIP_RE.match(s):
                        unmapped.add(s)
                continue
            period, ptype = resolved
            uom = 'LSM' if (block_uom == 'WSC' and lsm) else block_uom
            rows.append((instrument, period, ptype, uom, df.iloc[r, c]))
    return rows


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
    keepset_lsm = {inst.replace(' ', ''): lsm for (inst, lsm) in imap.values()}

    unmapped = set()
    rows = []
    rows += _parse_block(df, *_WSC_BLOCK, imap, periods, report_date, 'WSC', unmapped)
    rows += _parse_block(df, *_PMT_BLOCK, imap, periods, report_date, 'PMT', unmapped)
    rows += _parse_wsfr(df, imap, report_date)
    rows += _parse_bitr(df, keepset_lsm, report_date)
    if unmapped:
        print(f"JOSH parse [{file}]: unrecognized tenor label(s) dropped (possible format drift): {sorted(unmapped)}")
    return _assemble(rows, report_date)


def main(file):
    return readFile(file)


if __name__ == '__main__':
    print(main('2026-08-17.xlsx'))
