"""Independent Arelle XBRL 2.1 checks against an exported offline taxonomy package."""
import argparse,json,sys,subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--deps',required=True);parser.add_argument('--input',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    sys.path.insert(0,str(Path(args.deps).resolve()))
    from importlib.metadata import version
    base=Path(args.input).resolve();output=Path(args.out).resolve();output.mkdir(parents=True,exist_ok=False);reports=[]
    for number,path in enumerate(sorted(base.rglob('*.xbrl')),1):
        if 'LARGE_GL' in path.parts:continue
        log=output/f'{number:03d}.xml'
        bootstrap='import sys;sys.path.insert(0,'+repr(str(Path(args.deps).resolve()))+');from arelle.CntlrCmdLine import main;main()'
        process=subprocess.run([sys.executable,'-B','-X','utf8','-c',bootstrap,'--file',str(path),'--packages',str(path.parent/'xbrl-gl-2015-taxonomy.zip'),
                     '--workOffline','--disablePersistentConfig','--xdgConfigHome',str(output/'config'),
                     '--validate','--validationExitCode','--logFile',str(log)],capture_output=True,text=True,timeout=90)
        assert process.returncode==0,(str(path),process.stdout,process.stderr)
        entries=ET.parse(log).findall('entry')
        errors=[e.get('code') for e in entries if e.get('level','').startswith(('error','critical','fatal'))]
        warnings=[e.get('code') for e in entries if e.get('level','').startswith('warning')]
        messages=[e.findtext('message','') for e in entries]
        assert any('validated in ' in m for m in messages),messages
        assert not errors,(str(path),errors)
        reports.append({'file':path.relative_to(base).as_posix(),'errors':errors,'warnings':warnings,'validated':True,'offline':True})
    assert reports
    result={'validator':'Arelle','version':version('arelle-release'),'ok':True,'documents':reports}
    (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'validator':'Arelle','version':result['version'],'documents':len(reports),'errors':0,'warnings':sum(len(r['warnings']) for r in reports)},ensure_ascii=False))

if __name__=='__main__':main()
