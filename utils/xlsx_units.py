"""Resolve TD15/TD34 forwards from the explicitly unit-labelled Josh curve.

The Braemar XLSX has one unit heading per tenor column. Some TD15 and TD34
cells contain Worldscale under a $/Tonne heading (Jan-27 and Q1-27 on both
routes from 2026-11-02). The heading alone cannot establish the cell's actual
unit. Use the same-report-date Josh quote in the requested unit, as the
all-route master already does. Never guess units from magnitude or borrow
another day.
"""

import numpy as np
import pandas as pd


QUOTE_KEY = ['date', 'instrument', 'periodType', 'period', 'uom']
# Routes whose legacy forwards are taken from Josh. Every route here must be
# mapped in lookup/josh_instruments.csv, or the publication is held.
ROUTES = ('TD15', 'TD34')


def referenced_forwards(frame):
    return frame['instrument'].isin(ROUTES) & frame['periodType'].isin(['M', 'Q', 'A'])


def align_forwards(xlsx, josh):
    """Preserve the legacy schema/units, taking TD15/TD34 forwards from Josh.

    Only existing XLSX forward keys are selected; BITR, MTD and other routes
    remain untouched. Missing, duplicate or invalid reference quotes stop the
    publication before its master/windows are written. An observed zero is
    valid. Applying this to the whole master also repairs saved history.
    """
    result = xlsx.copy()
    selected = referenced_forwards(result)
    if not selected.any():
        return result

    targets = result.loc[selected, QUOTE_KEY]
    references = josh.loc[referenced_forwards(josh), QUOTE_KEY + ['value']]
    # Limit validation to quotes this export actually consumes. Do not make
    # unrelated Josh instruments or tenors a dependency of the legacy file.
    references = references.merge(targets, on=QUOTE_KEY, how='inner')
    matched = targets.merge(references, on=QUOTE_KEY, how='left', validate='one_to_one')
    values = pd.to_numeric(matched['value'], errors='coerce')
    invalid = (
        ~np.isfinite(values) | values.lt(0)
        | matched['value'].map(lambda value: isinstance(value, (bool, np.bool_)))
        | ~matched['uom'].isin(['WSC', 'PMT'])
    )
    if invalid.any():
        row = matched.loc[invalid].iloc[0]
        raise ValueError(
            f"{row['instrument']} publication held: missing or invalid same-date Josh quote "
            f"for {row['date']:%Y-%m-%d} {row['periodType']} "
            f"{row['period']:%b-%y} {row['uom']}. "
            'Update the Josh feed, then retry with --force; no XLSX files were published.'
        )

    result.loc[selected, 'value'] = values.to_numpy()
    return result


def frames_equal(left, right):
    """Compare saved observations, including amendments with no new rows."""
    return left.sort_values(QUOTE_KEY).reset_index(drop=True).equals(
        right.sort_values(QUOTE_KEY).reset_index(drop=True))


def changed_by_route(before, after):
    """Count forward quotes per route that the alignment changed."""
    changed = referenced_forwards(before) & before['value'].ne(after['value'])
    return before.loc[changed, 'instrument'].value_counts().sort_index().to_dict()


def repair_master(xlsx_path='./data/GFI_xlsx.csv', josh_path='./data/GFI_josh.csv'):
    """Read and validate a repair without writing or contacting Outlook/S3."""
    original = pd.read_csv(xlsx_path, parse_dates=['date', 'period'])
    if not referenced_forwards(original).any():
        return original, original.copy()
    josh = pd.read_csv(josh_path, parse_dates=['date', 'period'])
    return original, align_forwards(original, josh)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Check/repair TD15/TD34 units in the local XLSX master')
    parser.add_argument('--apply', action='store_true', help='write the validated local repair (no upload)')
    args = parser.parse_args()
    before, after = repair_master()
    counts = changed_by_route(before, after)
    for route in ROUTES:
        print(f'{route}: {counts.get(route, 0)} forward quote(s) differ from the same-date Josh feed')
    if args.apply and not frames_equal(before, after):
        after.to_csv('./data/GFI_xlsx.csv', index=False)
        print('Wrote local GFI_xlsx.csv. Run python main.py --force on Windows to publish all windows.')
    elif not args.apply:
        print('Check only: no files written or published.')
