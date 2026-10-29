"""Run harmless local security regressions against source or the real EXE."""
import csv
import json
from pathlib import Path
import sys
import time
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
if not getattr(sys, 'frozen', False):
    sys.path[:0] = [str(ROOT), str(ROOT / '.build-tools')]
from version import VERSION


def run_checks(folder):
    from application.configuration import default_profile, default_catalog
    from application.loading import load_batch
    from application.workfiles import load_work, save_work
    from application.diagnostics import write_error_event
    from core.errors import InputError
    from core.spreadsheet_text import csv_text
    from io_xlsx.package_guard import check_package
    from desktop.controllers.jobs import Job

    started = time.monotonic()
    root = Path(folder).resolve(); root.mkdir(parents=True, exist_ok=False)
    source = root / '합성보안검사.csv'
    headers = ['Corp', 'Day', 'Voucher', 'Seq', 'Code', 'Account', 'DR', 'CR']
    with source.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output); writer.writerow(headers)
        writer.writerows([['SYNTHETIC', '2026-01-02', 'J1', '1', '001', '보통예금', '100', '0'],
                          ['SYNTHETIC', '2026-01-02', 'J1', '2', '002', '상품매출', '0', '100']])
    profile = default_profile()
    profile.update(companyCode='SYNTHETIC', sourceSystem='SECURITY-FIXTURE',
        columnMappings={'gl': dict(zip(('company', 'date', 'journal', 'line', 'account', 'name', 'debit', 'credit'), headers))})
    profile['sheets']['gl'] = ['CSV']; profile['sheets']['fs'] = []
    session = load_batch([source], profile, default_catalog(), False)
    path = save_work(session, root / '정상업무.acwork')
    with ZipFile(path) as archive: entries = {name: archive.read(name) for name in archive.namelist()}
    reopened = load_work(path)
    try: assert reopened.result['counts']['sourceGlRows'] == 2
    finally: reopened._restored_temp.cleanup()
    data = json.loads(entries['manifest.json'])
    data['supportSetup'] = {'tables': {'시산표': {'path': str(root / 'not-attached.csv')}}}
    entries['manifest.json'] = json.dumps(data).encode('utf-8')
    malicious = root / '차단검사_업무.acwork'
    with ZipFile(malicious, 'w', ZIP_DEFLATED) as archive:
        for name, raw in entries.items(): archive.writestr(name, raw)
    try: load_work(malicious)
    except InputError as error: assert '첨부' in str(error)
    else: raise AssertionError('External support path accepted')
    xlsx = root / '차단검사_외부링크.xlsx'
    with ZipFile(xlsx, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('_rels/.rels', '<Relationships><Relationship TargetMode="External" Target="https://example.invalid/do-not-contact"/></Relationships>')
    try: check_package(xlsx)
    except InputError as error: assert '외부 링크' in str(error)
    else: raise AssertionError('External relationship accepted')

    marker = 'SYNTHETIC_ACCOUNT_000-999 C:/PRIVATE_SYNTHETIC/bank.xlsx'
    def fail(): raise InputError(marker)
    failures = []
    job = Job(fail); job.signals.failed.connect(lambda message, details: failures.append((message, details)))
    job.run()
    assert len(failures) == 1 and marker in failures[0][0]
    assert marker not in failures[0][1] and 'PRIVATE_SYNTHETIC' not in failures[0][1]
    event_id = write_error_event(failures[0][1], root / 'logs')
    raw_log = (root / 'logs/diagnostics.jsonl').read_text(encoding='utf-8')
    assert event_id and marker not in raw_log and 'PRIVATE_SYNTHETIC' not in raw_log
    assert json.loads(raw_log)['errorType'] == 'InputError'
    assert all(csv_text(text).startswith("'") for text in (' =1+1', '＠SUM(1)', '\n=1+1'))
    result = {'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)), 'ok': True,
        'syntheticOnly': True, 'legitimateWorkReopened': True, 'externalWorkSupportPathBlocked': True,
        'externalXlsxRelationshipBlocked': True, 'workerErrorSignalDelivered': True,
        'exceptionValuesAndPathsExcludedFromDiagnostic': True, 'firstExportCsvTextNeutralized': True,
        'networkUsed': False, 'osInputUsed': False, 'seconds': round(time.monotonic() - started, 3),
        'scope': 'Harmless local fixtures. Does not certify encryption, authenticity, runtime/OS security or absence of vulnerabilities.'}
    (root / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True)
    run_checks(parser.parse_args().out)
