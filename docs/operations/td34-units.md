# TD34 legacy export repair

## Source and scope

The legacy Braemar XLSX applies one unit heading to a whole tenor column.
Some TD34 values do not use that unit. In the published 6 November 2026 data,
Jan-27 was `307.980718 PMT` and Q1-27 was `222.281735 PMT`. The same-date Josh
curve explicitly reports Jan-27 as **57.50 PMT / 307.98 WSC** and Q1-27 as
**41.50 PMT / 222.28 WSC**. Reading the legacy Jan-27 number as dollars per
tonne causes a second conversion to roughly 1,650 Worldscale.

The correction is in the producer, before `GFI_xlsx.csv`, `_last`, `_30` and
`_60` are published. `utils/xlsx_units.py` takes every existing TD34 M/Q/A key
from the same-date Josh curve in the unit requested by the legacy schema.
Thus the repaired Jan-27 legacy row is **57.50 PMT**; the native all-route
parquet continues to expose both units. Monthly, quarterly and annual keys
remain distinct even when their contract start dates coincide.

This makes Josh authoritative for legacy TD34 forwards, consistent with
`gfi_master.parquet`. It also resolves genuine same-day differences between
the two reports in Josh's favor. It does not add new tenors or units, replace
missing prices with zero, borrow another date, change BITR/MTD or alter other
routes. Raw attachments are retained unchanged for tracing the source.

Required Josh quotes must be present, unique, finite and nonnegative. Zero
is a valid observation. Missing/invalid references stop XLSX publication,
leaving its previous master and windows intact. The error identifies the
contract to investigate. Do not bypass this by using the mislabeled XLSX
number or relabelling every future TD34 tenor as WSC.

Downloaded reports awaiting validation are recorded as `GFI_xlsx_pending` in
the ignored `data/state.json`. They bypass the daily run gate and are parsed
again from disk on retry, including amendments. The queue is cleared only
after a validated master is saved (or confirmed unchanged). Cursor and queue
updates replace the state file atomically.

## Apply on the Windows publisher

Update the code on the native publisher, preserving its newer data files,
`.env` and `data/state.json`. No market data files ship with this code change.
Run from the repository root in its normal Python environment:

```console
python -m utils.xlsx_units
python main.py --force
```

The first command checks the current local masters without writing or uploading.
If Josh is behind, the check fails; the full run downloads/compiles Josh before
reconciling XLSX. `--force` bypasses the once-per-day gate and reconciles the
whole saved history without needing old attachments to be downloaded again.
For a longer acquisition gap, use `python main.py --force --days 30`.

To write a validated local repair without any publication, use
`python -m utils.xlsx_units --apply`. This alone does not update the shortened
files or S3; the normal forced run must still publish them.

After a successful forced run, check the local master and published master/
applicable trailing windows. For report date 2026-11-06, confirm TD34 monthly
Jan-27 is 57.50 PMT, quarterly Q1-27 is 41.50 PMT, and BITR stays 545 WSC.
Check the run log for upload failures and K: copy errors; those existing
publication functions log failures without failing the entire process.

The consumers must then refresh/rebuild their affected history from these
corrected exports. An already cached `master_pricing`/WTINSEA value is not
repaired merely by updating this producer's code. Confirm the consumer's
source date and contract, rather than replacing the January forward with
November spot.

## Recovery and verification

If a required Josh quote is absent, restore/acquire that report, check its
explicit unit block, and retry `--force`. Do not fabricate a replacement.
If code rollback is necessary, preserve the corrected data and pause XLSX
publication until the unit guard is restored; the old exporter can recreate
the bad data on the next report.

Run `python -m pytest -q`. Regression coverage includes the November unit
error, original header parsing, exact-date matching, monthly versus quarterly
contracts, zeros, missing/invalid/duplicate references, historical repairs
with no new rows, same-row-count Josh amendments, all four CSV publications,
unchanged-run behavior, forced publication and failure without partial writes.
The tests do not contact Outlook, S3 or K: and keep generated files in temporary
directories. Native Outlook acquisition and live publication must be verified
on the publisher separately.
