"""TD15/TD34 unit regression and publication checks; all writes stay in tmp_path."""

import numpy as np
import pandas as pd
import pytest

import main as pipeline
from utils import read_xlsx_file, shorten_csv
from utils.state import get_pending_files, get_cursor, set_cursor
from utils.xlsx_units import align_forwards, changed_by_route, frames_equal


COLS = ['source', 'periodType', 'date', 'instrument', 'period', 'uom', 'value']


def quotes(rows):
    frame = pd.DataFrame(rows, columns=COLS)
    for col in ['date', 'period']:
        frame[col] = pd.to_datetime(frame[col])
    return frame


@pytest.fixture
def november_quotes():
    # Reviewed Nov 6 Jan/Q1-27 regression: these XLSX values are Worldscale
    # despite their PMT headings. The explicit curve has both native units.
    xlsx = quotes([
        ['GFI', 'M', '2026-11-06', 'TD34', '2027-01-01', 'PMT', 307.980718],
        ['GFI', 'Q', '2026-11-06', 'TD34', '2027-01-01', 'PMT', 222.281735],
        ['GFI', 'M', '2026-11-06', 'TD34', '2026-12-01', 'WSC', 400.0],
        ['GFI', 'BITR', '2026-11-06', 'TD34', '2026-11-01', 'WSC', 545.0],
        ['GFI', 'M', '2026-11-06', 'TD25', '2027-01-01', 'PMT', 66.0],
        ['GFI', 'MTD', '2026-11-06', 'TD34', '2026-11-01', 'WSC', 550.0],
        ['GFI', 'M', '2026-11-06', 'TD15', '2027-01-01', 'PMT', 287.356322],
        ['GFI', 'Q', '2026-11-06', 'TD15', '2027-01-01', 'PMT', 257.108288],
    ])
    josh = quotes([
        ['GFI', 'M', '2026-11-06', 'TD34', '2027-01-01', 'PMT', 57.5],
        ['GFI', 'M', '2026-11-06', 'TD34', '2027-01-01', 'WSC', 307.98],
        ['GFI', 'Q', '2026-11-06', 'TD34', '2027-01-01', 'PMT', 41.5],
        ['GFI', 'Q', '2026-11-06', 'TD34', '2027-01-01', 'WSC', 222.28],
        ['GFI', 'M', '2026-11-06', 'TD34', '2026-12-01', 'WSC', 400.0],
        ['GFI', 'M', '2026-11-06', 'TD15', '2027-01-01', 'PMT', 95.0],
        ['GFI', 'M', '2026-11-06', 'TD15', '2027-01-01', 'WSC', 287.36],
        ['GFI', 'Q', '2026-11-06', 'TD15', '2027-01-01', 'PMT', 85.0],
        ['GFI', 'Q', '2026-11-06', 'TD15', '2027-01-01', 'WSC', 257.11],
    ])
    return xlsx, josh


def test_november_units_and_scope(november_quotes):
    xlsx, josh = november_quotes
    original = xlsx.copy()
    fixed = align_forwards(xlsx, josh)
    assert fixed['value'].tolist() == [57.5, 41.5, 400.0, 545.0, 66.0, 550.0, 95.0, 85.0]
    assert changed_by_route(xlsx, fixed) == {'TD15': 2, 'TD34': 2}
    pd.testing.assert_frame_equal(fixed.drop(columns='value'), xlsx.drop(columns='value'))
    pd.testing.assert_frame_equal(xlsx, original)
    pd.testing.assert_frame_equal(align_forwards(fixed, josh), fixed)
    assert fixed.iloc[0]['value'] / 18.67 * 100 == pytest.approx(307.98, abs=.005)
    assert fixed.iloc[6]['value'] / 33.06 * 100 == pytest.approx(287.36, abs=.005)


def test_header_parser_to_unit_resolution(monkeypatch, november_quotes):
    raw = pd.DataFrame([
        [np.nan, np.nan, np.nan, np.nan],
        [np.nan, np.nan, np.nan, np.nan],
        ['6 Nov 2026', np.nan, np.nan, np.nan],
        [np.nan, np.nan, np.nan, np.nan],
        [np.nan, 'Route', np.nan, 'Jan-27'],
        [np.nan, np.nan, 'BITR', '$/Tonne'],
        [np.nan, 'TD34', 545.0, 307.980718],
    ])
    monkeypatch.setattr(read_xlsx_file.pd, 'read_excel', lambda *a, **k: raw)
    parsed = read_xlsx_file.readFile('2026-11-06.xlsx')
    fixed = align_forwards(parsed, november_quotes[1])
    forward = fixed[fixed.periodType.eq('M')].iloc[0]
    assert forward['period'] == pd.Timestamp('2027-01-01')
    assert forward['uom'] == 'PMT'
    assert forward['value'] == 57.5


@pytest.mark.parametrize('bad', [np.nan, np.inf, -1.0, True, 'not a quote'])
def test_invalid_reference_stops_repair(november_quotes, bad):
    xlsx, josh = november_quotes
    josh['value'] = josh['value'].astype(object)
    josh.loc[0, 'value'] = bad
    with pytest.raises(ValueError, match='TD34 publication held'):
        align_forwards(xlsx, josh)


def test_missing_reference_does_not_borrow_another_day_or_unit(november_quotes):
    xlsx, josh = november_quotes
    josh.loc[0, 'date'] = pd.Timestamp('2026-11-05')
    with pytest.raises(ValueError, match='2026-11-06 M Jan-27 PMT'):
        align_forwards(xlsx, josh)


def test_each_route_needs_its_own_reference(november_quotes):
    xlsx, josh = november_quotes
    missing = josh.instrument.eq('TD15') & josh.periodType.eq('Q') & josh.uom.eq('PMT')
    with pytest.raises(ValueError, match='TD15 publication held.*2026-11-06 Q Jan-27 PMT'):
        align_forwards(xlsx, josh[~missing])


def test_duplicate_reference_is_not_silently_selected(november_quotes):
    xlsx, josh = november_quotes
    with pytest.raises(pd.errors.MergeError):
        align_forwards(xlsx, pd.concat([josh, josh.iloc[[0]]]))


def test_zero_and_annual_quote_use_explicit_unit(november_quotes):
    xlsx, josh = november_quotes
    xlsx = xlsx.iloc[[0]].copy()
    xlsx['periodType'] = 'A'
    josh = xlsx.copy()
    josh['value'] = 0.0
    assert align_forwards(xlsx, josh).iloc[0]['value'] == 0.0


def test_no_referenced_route_does_not_need_reference(november_quotes):
    xlsx = november_quotes[0].iloc[[4]].copy()
    pd.testing.assert_frame_equal(align_forwards(xlsx, pd.DataFrame()), xlsx)


def test_other_routes_missing_prices_are_preserved(november_quotes):
    xlsx, josh = november_quotes
    xlsx.loc[xlsx.instrument.eq('TD25'), 'value'] = np.nan
    fixed = align_forwards(xlsx, josh)
    assert pd.isna(fixed.loc[4, 'value'])


def local_pipeline(tmp_path, monkeypatch, xlsx, josh):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    xlsx.to_csv('data/GFI_xlsx.csv', index=False)
    josh.to_csv('data/GFI_josh.csv', index=False)
    monkeypatch.setattr(pipeline, 'get_cursor', lambda name: None)
    monkeypatch.setattr(pipeline, 'downloader_xlsx', lambda *a: ([], None))
    monkeypatch.setattr(pipeline, 'mtdFromCsvMaster', lambda: xlsx.iloc[0:0])
    monkeypatch.setattr(pipeline, 'copyToKDrive', lambda paths: None)
    uploads = []
    monkeypatch.setattr(shorten_csv, 'uploadToCloud', lambda path, cloud: uploads.append(path))
    # Fixed clock makes the historical regression exercise every trailing window.
    class ReportDay(shorten_csv.datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 8)
    monkeypatch.setattr(shorten_csv.datetime, 'date', ReportDay)
    return uploads


def test_saved_history_and_all_windows_are_repaired_without_new_rows(
        tmp_path, monkeypatch, november_quotes):
    xlsx, josh = november_quotes
    uploads = local_pipeline(tmp_path, monkeypatch, xlsx, josh)
    result = pipeline.xlsxDownloader(5)
    assert len(result) == len(xlsx)
    assert len(uploads) == 4
    for path in uploads:
        published = pd.read_csv(path, parse_dates=['date', 'period'])
        assert published.iloc[0]['value'] == 57.5
        assert published.iloc[1]['value'] == 41.5
        assert published.iloc[6]['value'] == 95.0
        assert published.iloc[7]['value'] == 85.0
        assert len(published) == len(xlsx)
    assert pipeline.xlsxDownloader(5) is None  # repeat is quiet/idempotent
    assert len(uploads) == 4
    pipeline.xlsxDownloader(5, force=True)
    assert len(uploads) == 8  # --force still republishes a repaired master


def test_failed_repair_preserves_file_and_does_not_upload(tmp_path, monkeypatch, november_quotes):
    xlsx, josh = november_quotes
    uploads = local_pipeline(tmp_path, monkeypatch, xlsx, josh.iloc[1:])
    path = tmp_path / 'data/GFI_xlsx.csv'
    original = path.read_bytes()
    with pytest.raises(ValueError, match='TD34 publication held'):
        pipeline.xlsxDownloader(5, force=True)
    assert path.read_bytes() == original
    assert not uploads
    assert not (tmp_path / 'data/shortened').exists()


def test_josh_amendment_is_saved_at_same_row_count(tmp_path, monkeypatch, november_quotes):
    xlsx, josh = november_quotes
    uploads = local_pipeline(tmp_path, monkeypatch, xlsx, josh)
    amendment = josh.iloc[[0]].copy()
    amendment['value'] = 58.0
    monkeypatch.setattr(pipeline, 'downloader_josh', lambda *a: (['2026-11-06.xlsx'], None))
    monkeypatch.setattr(pipeline, 'read_josh_file', lambda file: amendment)
    result = pipeline.joshDownloader(5)
    assert len(result) == len(josh)
    saved = pd.read_csv('data/GFI_josh.csv', parse_dates=['date', 'period'])
    amended = saved.instrument.eq('TD34') & saved.uom.eq('PMT') & saved.periodType.eq('M')
    assert saved[amended]['value'].tolist() == [58.0]
    assert len(uploads) == 4


def test_josh_runs_before_xlsx_even_on_force(monkeypatch):
    calls = []
    for name in ['csvCompiler', 'joshDownloader', 'xlsxDownloader', 'build_cash_arb', 'build_gfi_master']:
        monkeypatch.setattr(pipeline, name, lambda *a, name=name: calls.append(name))
    monkeypatch.setattr(pipeline, 'runFunctionCheck', False)
    pipeline.main(5, force=True)
    assert calls == ['csvCompiler', 'joshDownloader', 'xlsxDownloader', 'build_cash_arb', 'build_gfi_master']


@pytest.mark.parametrize('amendment', [False, True])
def test_held_report_retries_from_disk_without_another_download(
        tmp_path, monkeypatch, november_quotes, amendment):
    xlsx, josh = november_quotes
    # Start with a valid previous publication, then receive either a new date
    # or a same-date amendment whose matching Josh quote is temporarily absent.
    prior = align_forwards(xlsx, josh)
    uploads = local_pipeline(tmp_path, monkeypatch, prior, josh)
    incoming = xlsx.iloc[[0]].copy()
    if not amendment:
        incoming['date'] = pd.Timestamp('2026-11-09')
    else:
        # A new contract on an amendment also needs its own matching reference.
        incoming['period'] = pd.Timestamp('2027-02-01')
    name = incoming.iloc[0]['date'].strftime('%Y-%m-%d') + '.xlsx'
    reads = []
    def parse(file):
        reads.append(file)
        return incoming
    monkeypatch.setattr(pipeline, 'read_xlsx_file', parse)
    monkeypatch.setattr(pipeline, 'downloader_xlsx', lambda *a: ([name], None))
    with pytest.raises(ValueError, match='TD34 publication held'):
        pipeline.xlsxDownloader(5)
    assert get_pending_files('GFI_xlsx') == [name]
    assert not uploads

    # Cursor updates for other feeds preserve the pending-file list.
    cursor = pd.Timestamp('2026-11-09 12:00:00').to_pydatetime()
    set_cursor('GFI_josh', cursor)
    assert get_cursor('GFI_josh') == cursor
    assert get_pending_files('GFI_xlsx') == [name]

    reference = incoming.copy()
    reference['value'] = 58.0
    pd.concat([josh, reference]).to_csv('data/GFI_josh.csv', index=False)
    monkeypatch.setattr(pipeline, 'downloader_xlsx', lambda *a: ([], None))
    repaired = pipeline.xlsxDownloader(5)
    assert repaired.iloc[-1]['value'] == 58.0
    assert reads == [name, name]
    assert not get_pending_files('GFI_xlsx')
    assert len(uploads) == 4


def test_pending_report_bypasses_daily_gate(tmp_path, monkeypatch):
    from utils.state import set_pending_files
    monkeypatch.chdir(tmp_path)
    set_pending_files('GFI_xlsx', ['2026-11-06.xlsx'])
    monkeypatch.setattr(pipeline, 'runFunctionCheck', False)
    calls = []
    for name in ['csvCompiler', 'joshDownloader', 'xlsxDownloader', 'build_cash_arb', 'build_gfi_master']:
        monkeypatch.setattr(pipeline, name, lambda *a, name=name: calls.append(name))
    pipeline.main(5)
    assert calls == ['csvCompiler', 'joshDownloader', 'xlsxDownloader', 'build_cash_arb', 'build_gfi_master']


def test_change_detection_includes_units_and_ignores_order(november_quotes):
    xlsx = november_quotes[0]
    assert frames_equal(xlsx, xlsx.iloc[::-1])
    changed = xlsx.copy()
    changed.loc[0, 'uom'] = 'WSC'
    assert not frames_equal(xlsx, changed)
    assert not frames_equal(xlsx, xlsx.iloc[1:])


def test_change_detection_ignores_last_bit_float_noise(november_quotes):
    # The saved CSV can parse back one bit away from the recomputed TD22 MTD
    # (price / 1e6); that is not a changed quote, but a real move still is.
    xlsx = november_quotes[0]
    noisy = xlsx.copy()
    noisy['value'] = np.nextafter(noisy['value'], np.inf)
    assert not noisy['value'].equals(xlsx['value'])
    assert frames_equal(xlsx, noisy)
    moved = xlsx.copy()
    moved.loc[0, 'value'] += 0.01
    assert not frames_equal(xlsx, moved)
    missing = xlsx.copy()
    missing.loc[0, 'value'] = np.nan
    assert not frames_equal(xlsx, missing)
    assert frames_equal(missing, missing.copy())


def test_idle_run_with_mtd_float_noise_does_not_republish(tmp_path, monkeypatch, november_quotes):
    xlsx, josh = november_quotes
    xlsx = align_forwards(xlsx, josh)
    uploads = local_pipeline(tmp_path, monkeypatch, xlsx, josh)
    mtd = xlsx[xlsx.periodType.eq('MTD')].copy()
    mtd['value'] = np.nextafter(mtd['value'], np.inf)
    monkeypatch.setattr(pipeline, 'mtdFromCsvMaster', lambda: mtd)
    before = (tmp_path / 'data/GFI_xlsx.csv').read_bytes()
    assert pipeline.xlsxDownloader(5) is None
    assert not uploads
    assert (tmp_path / 'data/GFI_xlsx.csv').read_bytes() == before
