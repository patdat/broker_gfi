"""Unrecognized-tenor-label drift logging assertions for read_josh_file.
Run from repo root with the venv python."""

import contextlib
import io
import os
import sys
import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_josh_file

FILE = '2026-08-17.xlsx'


def test_no_false_positive_on_real_fixture():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        read_josh_file.main(FILE)
    captured = buf.getvalue()
    assert 'unrecognized tenor label' not in captured, (
        f'unexpected drift line for well-formed fixture: {captured!r}')


def test_classifier_distinguishes_drift_from_strip():
    periods = read_josh_file.load_periods()
    report_date = pd.Timestamp('2026-08-17')

    # genuinely unrecognized label -> dropped (None), and NOT a recognized strip
    assert read_josh_file.resolve_tenor('Zqx-99', report_date, periods) is None
    assert read_josh_file._STRIP_RE.match('Zqx-99') is None

    # deliberate month-range strip -> also dropped (None), but IS a recognized strip
    assert read_josh_file.resolve_tenor("Aug-Dec'26", report_date, periods) is None
    assert read_josh_file._STRIP_RE.match("Aug-Dec'26") is not None


if __name__ == '__main__':
    test_no_false_positive_on_real_fixture()
    test_classifier_distinguishes_drift_from_strip()
    print('test_drift_logging OK')
