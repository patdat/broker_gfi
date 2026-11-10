# TD15/TD34 legacy export repair

## Source and scope

The legacy Braemar XLSX applies one unit heading to a whole tenor column.
Some TD34 and TD15 values do not use that unit. In the published 6 November
2026 data, TD34 Jan-27 was `307.980718 PMT` and Q1-27 `222.281735 PMT`; TD15
Jan-27 was `287.356322 PMT` and Q1-27 `257.108288 PMT`. The same-date Josh
curve explicitly reports TD34 Jan-27 as **57.50 PMT / 307.98 WSC** and TD15
Jan-27 as **95.00 PMT / 287.36 WSC**. Reading the legacy Jan-27 number as
dollars per tonne causes a second conversion to roughly 1,650 (TD34) or 870
(TD15) Worldscale. The TD15 error has been present since 2026-11-02.

The correction is in the producer, before `GFI_xlsx.csv`, `_last`, `_30` and
`_60` are published. `utils/xlsx_units.py` takes every existing M/Q/A key of
the routes in its `ROUTES` tuple (TD15, TD34) from the same-date Josh curve in
the unit requested by the legacy schema. Thus the repaired TD34 Jan-27 legacy
row is **57.50 PMT** and TD15's is **95.00 PMT**; the native all-route parquet
continues to expose both units. Monthly, quarterly and annual keys remain
distinct even when their contract start dates coincide.

This makes Josh authoritative for these legacy forwards, consistent with
`gfi_master.parquet`. It also resolves genuine same-day differences between
the two reports in Josh's favor. It does not add new tenors or units, replace
missing prices with zero, borrow another date, change BITR/MTD or alter other
routes. Raw attachments are retained unchanged for tracing the source.

Josh quotes TD15 since 2026-09-14 (and once on 2026-08-24), before the xlsx
feed added the route on 2026-10-07, so every legacy TD15 forward has a
reference. TD15 was added to `lookup/josh_instruments.csv` on 2026-11-09; the
Josh master was re-compiled from the raw Curves files on disk to backfill it.

Required Josh quotes must be present, unique, finite and nonnegative. Zero
is a valid observation. Missing/invalid references stop XLSX publication,
leaving its previous master and windows intact. The error identifies the
route and contract to investigate. Do not bypass this by using the mislabeled
XLSX number or relabelling every future forward tenor as WSC. Adding a route
to `ROUTES` requires it to be mapped in `lookup/josh_instruments.csv` and
present in Josh for every date the xlsx quotes it.

Downloaded reports awaiting validation are recorded as `GFI_xlsx_pending` in
the ignored `data/state.json`. They bypass the daily run gate and are parsed
again from disk on retry, including amendments. The queue is cleared only
after a validated master is saved (or confirmed unchanged). Cursor and queue
updates replace the state file atomically.

Change detection compares keys and units exactly and values within a `1e-12`
relative tolerance. The TD22 MTD carry-over is recomputed each run as price/1e6
and can differ in its last bit from the value parsed back from the saved CSV.
An exact comparison treated that as a changed quote, so every idle run rewrote
and re-uploaded the legacy files (2026-11-09 08:30 to 2026-11-10).

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
Jan-27 is 57.50 PMT, quarterly Q1-27 is 41.50 PMT, TD15 monthly Jan-27 is
95.00 PMT, quarterly Q1-27 is 85.00 PMT, and TD34 BITR stays 545 WSC.
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
error on both routes, original header parsing, exact-date matching, monthly
versus quarterly contracts, zeros, missing/invalid/duplicate references,
per-route reference requirements, historical repairs with no new rows,
same-row-count Josh amendments, all four CSV publications, unchanged-run
behavior, forced publication and failure without partial writes.
The tests do not contact Outlook, S3 or K: and keep generated files in temporary
directories. Native Outlook acquisition and live publication must be verified
on the publisher separately.
