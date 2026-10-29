"""Explicit, metadata-only inventory/OSV check; never called by the desktop app."""
import argparse
from datetime import datetime, timezone
from email.parser import Parser
from importlib.metadata import distribution, PackageNotFoundError
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.build-tools')]
from version import VERSION


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).casefold()


def inventory(runtime):
    """Use the bundled metadata when present, build metadata for license-only deps."""
    runtime = Path(runtime)
    if not (runtime / 'AccountDataNormalizer.exe').is_file() or not (runtime / 'licenses').is_dir():
        raise ValueError('검증할 Windows 실행팩 폴더를 선택해 주세요.')
    metadata = {}
    for path in sorted((runtime / '_internal').glob('*.dist-info/METADATA')):
        if path.stat().st_size > 1024**2: raise ValueError('패키지 메타데이터 크기 한도 초과')
        parsed = Parser().parsestr(path.read_text(encoding='utf-8'))
        if parsed.get('Name') and parsed.get('Version'):
            key = canonical(parsed['Name'])
            if key in metadata and metadata[key][1] != parsed['Version']:
                raise ValueError('동일 패키지의 버전 근거가 충돌합니다: ' + parsed['Name'])
            metadata[key] = (parsed['Name'], parsed['Version'], 'packaged-metadata')
    names = {path.name for path in (runtime / 'licenses').iterdir() if path.is_dir()}
    for name in names:
        if canonical(name) in metadata: continue
        try:
            package = distribution(name)
        except PackageNotFoundError as exc:
            raise ValueError('버전 근거가 없는 패키지: ' + name) from exc
        metadata[canonical(name)] = (package.metadata['Name'], package.version, 'build-environment-metadata')
    result = []
    for name, version, evidence in sorted(metadata.values(), key=lambda item: canonical(item[0])):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name) or not re.fullmatch(r'[A-Za-z0-9_.+!-]{1,100}', version):
            raise ValueError('패키지 이름·버전 메타데이터 형식 오류')
        result.append({'name': name, 'version': version, 'versionEvidence': evidence})
    if not result: raise ValueError('확인할 패키지 메타데이터가 없습니다.')
    return result


def query_osv(packages):
    # The only outbound data are public package names and versions. Cookies,
    # credentials, local paths and accounting input are not part of this API.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    pending = [{'package': {'ecosystem': 'PyPI', 'name': item['name']}, 'version': item['version']}
               for item in packages]
    findings = {canonical(item['name']): set() for item in packages}
    for _ in range(10):
        payload = json.dumps({'queries': pending}, separators=(',', ':')).encode('utf-8')
        request = Request('https://api.osv.dev/v1/querybatch', data=payload,
                          headers={'Content-Type': 'application/json', 'User-Agent': 'account-normalizer-dependency-check'}, method='POST')
        with opener.open(request, timeout=45) as response:
            raw = response.read(4 * 1024**2 + 1)
        if len(raw) > 4 * 1024**2: raise ValueError('OSV 응답 크기 한도 초과')
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get('results'), list) or len(result['results']) != len(pending):
            raise ValueError('OSV 응답 목록 형식 오류')
        next_queries = []
        for query, item in zip(pending, result['results']):
            if not isinstance(item, dict): raise ValueError('OSV 응답 항목 형식 오류')
            for advisory in item.get('vulns', []):
                identifier = advisory.get('id') if isinstance(advisory, dict) else None
                if not isinstance(identifier, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', identifier):
                    raise ValueError('OSV 취약점 ID 형식 오류')
                findings[canonical(query['package']['name'])].add(identifier)
            if item.get('next_page_token'):
                token = item['next_page_token']
                if not isinstance(token, str) or len(token) > 8192: raise ValueError('OSV 페이지 형식 오류')
                next_queries.append(dict(query, page_token=token))
        pending = next_queries
        if not pending: break
    if pending: raise ValueError('OSV 조회 페이지 한도를 넘었습니다. 검사를 완료하지 못했습니다.')
    return [{'package': item['name'], 'version': item['version'], 'ids': sorted(findings[canonical(item['name'])])}
            for item in packages if findings[canonical(item['name'])]]


def run(runtime, out, online=False):
    packages = inventory(runtime)
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    components = [{'type': 'library', 'name': item['name'], 'version': item['version'],
        'bom-ref': f"pkg:pypi/{canonical(item['name'])}@{quote(item['version'], safe='')}",
        'purl': f"pkg:pypi/{canonical(item['name'])}@{quote(item['version'], safe='')}",
        'properties': [{'name': 'account-normalizer:version-evidence', 'value': item['versionEvidence']}]}
        for item in packages]
    sbom = {'bomFormat': 'CycloneDX', 'specVersion': '1.6', 'serialNumber': 'urn:uuid:' + str(uuid4()), 'version': 1,
        'metadata': {'timestamp': stamp, 'component': {'type': 'application', 'name': 'account-data-normalizer', 'version': VERSION},
            'properties': [{'name': 'account-normalizer:inventory-scope',
                'value': 'Python distribution metadata and packaged license inventory. Build-only packages can be included. Native DLLs, OS and separately installed Ollama/models are outside this inventory.'}]},
        'components': components}
    status, findings, error_type = 'not-requested', [], None
    if online:
        try:
            findings = query_osv(packages)
            status = 'findings' if findings else 'no-known-advisories-returned'
        except Exception as error:
            status, error_type = 'incomplete', type(error).__name__
    report = {'schema': 'account-normalizer-dependency-audit/1', 'applicationVersion': VERSION,
        'checkedAt': stamp, 'source': 'https://api.osv.dev/v1/querybatch' if online else None,
        'status': status, 'packageCount': len(packages), 'packages': packages, 'findings': findings,
        'errorType': error_type, 'accountingDataSent': False, 'credentialsUsed': False,
        'scope': 'Known OSV advisories for the inventoried Python package versions at check time. No binary authenticity, native dependency, exploitability or absence-of-vulnerabilities certification.'}
    target = Path(out); target.mkdir(parents=True, exist_ok=True)
    for name, value in [('software-bom.json', sbom), ('dependency-audit.json', report)]:
        (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': status, 'packages': len(packages), 'affectedPackages': len(findings), 'errorType': error_type}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-dir', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--online', action='store_true', help='공개 패키지 이름·버전만 OSV에 조회합니다.')
    args = parser.parse_args()
    report = run(args.runtime_dir, args.out, args.online)
    raise SystemExit(1 if report['status'] in ('findings', 'incomplete') else 0)
