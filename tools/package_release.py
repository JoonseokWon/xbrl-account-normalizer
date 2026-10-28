"""Allowlisted release packaging; never runs business-data checks."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile,ZIP_DEFLATED
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from version import VERSION

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    release=ROOT/'배포'/('v'+VERSION);release.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/'dist'/VERSION/'AccountDataNormalizer'
    executable=runtime/'AccountDataNormalizer.exe'
    if not executable.is_file():raise FileNotFoundError('Windows EXE를 먼저 빌드하세요.')
    names=['.gitignore','README.md','version.py','main.py','convert.py','normalizer.py','suggestions.py',
           'review_history.py','field_mapping.py','workbook_export.py','demo_data.py','requirements.txt',
           'requirements-build.txt','설치.cmd','변환실행.cmd']
    files=[ROOT/name for name in names]
    for folder in ('core','application','desktop','io_xlsx','xbrl_gl','xbrl_filing'):
        files.extend(sorted((ROOT/folder).rglob('*.py')))
    for folder in ('config','docs','tests'):
        files.extend(sorted(path for path in (ROOT/folder).rglob('*') if path.is_file() and path.suffix in ('.json','.md','.py')))
    files.extend(ROOT/name for name in ('tools/create_demo.py','tools/verify_roundtrip.py','tools/build_windows.py','tools/package_release.py',
                                      'samples/계정매핑_합성입력.xlsx','assets/app-icon.svg','assets/fonts/NotoSansKR.ttf','assets/fonts/OFL.txt'))
    files.extend(sorted((ROOT/'assets/licenses').glob('*.txt')))
    files.extend(sorted((ROOT/'docs').glob('*.txt')))
    files.extend(ROOT/name for name in ('tools/run_audit_demo.py','tools/verify_audit_demo_import.py','tools/verify_company_workflow.py','tools/verify_company_import.py','tools/verify_desktop.py','tools/verify_large_audit_export.py'))
    files.extend(sorted(path for path in (ROOT/'samples/새회사변환예제').glob('*') if path.is_file() and path.suffix in ('.xlsx','.json','.md')))
    files.extend(ROOT/name for name in ('tools/company_cases.py','tools/prepare_company_cases.py','tools/create_company_workbooks.mjs',
                                      'tools/verify_company_mapping.py','tools/verify_multi_audit_import.py'))
    files.extend(sorted(path for path in (ROOT/'samples/여러회사매핑').glob('*') if path.is_file() and path.suffix in ('.xlsx','.json','.md')))
    files.extend(sorted(path for path in (ROOT/'vendor/xbrl-gl-2015').rglob('*') if path.is_file()))
    files.extend(ROOT/name for name in ('tools/fetch_xbrl_taxonomy.py','tools/verify_xbrl.py','tools/verify_xbrl_arelle.py'))
    files.append(ROOT/'tools/verify_xbrl_ui.py')
    files.append(ROOT/'tools/verify_filing.py')
    files.append(ROOT/'tools/verify_filing_ui.py')
    files.append(ROOT/'tools/verify_official_writer.py')
    entries=[]
    for path in files:
        if not path.resolve().is_relative_to(ROOT) or not path.is_file():raise ValueError('프로젝트 밖 또는 누락된 배포 파일')
        if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path.relative_to(ROOT)))
        if path.suffix=='.json':json.loads(path.read_text(encoding='utf-8-sig'))
        entries.append({'file':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':digest(path)})
    # Documentation may finish after the binary build. Copy the final versions.
    for name in ('README.md','docs/MANUAL_VALIDATION.md','docs/RELEASE_NOTES.md','docs/THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT/name,runtime/Path(name).name)
    (runtime/'docs').mkdir(exist_ok=True)
    for path in (ROOT/'docs').iterdir():
        if path.is_file() and path.suffix in ('.md','.txt'):shutil.copy2(path,runtime/'docs'/path.name)
    diagnostics=release/'exe-startup.json'
    subprocess.run([str(executable),'--diagnostics',str(diagnostics)],cwd=ROOT,
                   check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    startup=json.loads(diagnostics.read_text(encoding='utf-8-sig'))
    if startup.get('version')!=VERSION or not startup.get('frozen') or not all(startup.get('resources',{}).values()):
        raise ValueError('이 버전 EXE의 시작·리소스 확인 기록이 필요합니다.')
    evidence_path=release/'validation-summary.json'
    evidence=json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.exists() else None
    if evidence and evidence.get('version')!=VERSION:raise ValueError('다른 버전의 검증 기록입니다.')
    manifest={'version':VERSION,'validationStatus':'회사별 입력·업무 저장·시험 원장 변환 검증 완료; 실사용 확인 필요' if evidence else '사용자 검증 대기',
              'applicationTestsRun':bool(evidence and evidence.get('unitTestsPassed')),'validation':evidence,
              'initialUiRendered':(release/'화면_초안.png').is_file(),'exeStartup':startup,
              'sourceFileCount':len(entries),'pythonModuleCount':sum(path.suffix=='.py' for path in files),
              'exe':{'name':executable.name,'sha256':digest(executable),'bytes':executable.stat().st_size},'files':entries}
    manifest_path=release/'release-manifest.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    source_zip=release/f'account-data-normalizer-{VERSION}-source.zip'
    windows_zip=release/f'account-data-normalizer-{VERSION}-windows-x64.zip'
    with ZipFile(source_zip,'x',ZIP_DEFLATED) as output:
        for path in files:output.write(path,'account-data-normalizer/'+path.relative_to(ROOT).as_posix())
        output.write(manifest_path,'account-data-normalizer/release-manifest.json')
    with ZipFile(windows_zip,'x',ZIP_DEFLATED) as output:
        for path in sorted(runtime.rglob('*')):
            if path.is_file():output.write(path,'AccountDataNormalizer/'+path.relative_to(runtime).as_posix())
    checksum_files=[windows_zip,source_zip,manifest_path]
    checksum_files.extend(path for path in (release/'demo-conversion-pack.zip',release/'validation-summary.json') if path.is_file())
    checksums=''.join(f'{digest(path)}  {path.name}\n' for path in checksum_files)
    (release/'SHA256SUMS.txt').write_text(checksums,encoding='utf-8')
    print(json.dumps({'windows':str(windows_zip),'source':str(source_zip),'sourceFileCount':len(entries),
                      'pythonModuleCount':manifest['pythonModuleCount'],'applicationTestsRun':manifest['applicationTestsRun']},ensure_ascii=False))

if __name__=='__main__':main()
