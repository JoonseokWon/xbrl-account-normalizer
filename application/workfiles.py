"""Portable work files contain exact input bytes, a dictionary, and explicit reviews."""
import hashlib,json,os,tempfile
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED,BadZipFile
from core.catalog import catalog_index
from core.errors import InputError
from core.limits import MAX_FILES,MAX_EXPANDED_BYTES
from normalizer import normalize
from .loading import load_batch
from .paths import user_data

SCHEMA='account-normalizer-work/1'

def save_work(session,path,reviewer=''):
    path=Path(path)
    if path.suffix.lower()!='.acwork':raise InputError('업무 파일 확장자는 .acwork를 사용해 주세요.')
    paths=session.input_paths or (session.input_path,)
    expected=session.source.get('files',[session.source]);inputs=[]
    for i,source in enumerate(paths,1):
        raw=Path(source).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=expected[i-1]['sha256']:raise InputError('불러온 이후 원본이 변경되었습니다. 새 작업으로 다시 불러와 주세요.')
        inputs.append({'entry':f'inputs/{i:03d}{Path(source).suffix.lower()}','name':Path(source).name,'sha256':digest,'data':raw})
    support_setup=deepcopy(session.support_setup);support_inputs=[]
    for i,(table,spec) in enumerate(support_setup.get('tables',{}).items(),1):
        source=Path(spec['path']);raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        prior=next((s for s in session.support_bundle.source['sources'] if s['table']==table),{}) if session.support_bundle else {}
        if digest!=prior.get('sha256'):raise InputError('연결한 보조자료가 변경되었습니다. 보조자료를 다시 연결해 주세요.')
        entry=f'support/{i:03d}{source.suffix.lower()}';support_inputs.append({'entry':entry,'name':source.name,'sha256':digest,'table':table,'data':raw});spec['path']=entry
    if sum(len(i['data']) for i in inputs+support_inputs)>MAX_EXPANDED_BYTES:raise InputError('업무에 보관할 원본 합계가 250MB를 초과했습니다.')
    manifest={'schema':SCHEMA,'profile':session.profile,'catalog':session.catalog,'mappings':session.result['mappings'],
              'reviewer':reviewer,'inputs':[{k:v for k,v in item.items() if k!='data'} for item in inputs],
              'supportSetup':support_setup,'supportInputs':[{k:v for k,v in item.items() if k!='data'} for item in support_inputs]}
    path.parent.mkdir(parents=True,exist_ok=True)
    handle,name=tempfile.mkstemp(prefix='.work-',dir=path.parent);os.close(handle)
    try:
        with ZipFile(name,'w',ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
            for item in inputs+support_inputs:archive.writestr(item['entry'],item['data'])
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()
    session.job_path=path;session.dirty=False
    return path

def load_work(path):
    path=Path(path)
    if path.stat().st_size>MAX_EXPANDED_BYTES:raise InputError('업무 파일이 250MB를 초과했습니다.')
    temporary=None
    try:
        with ZipFile(path) as archive:
            infos=archive.infolist();names=[i.filename for i in infos]
            if len(names)!=len(set(names)) or len(names)>MAX_FILES+6 or sum(i.file_size for i in infos)>MAX_EXPANDED_BYTES+16*1024**2:
                raise InputError('업무 압축 구조·크기 한도를 확인해 주세요.')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>16*1024**2:raise InputError('업무 설정 파일이 없거나 너무 큽니다.')
            data=json.loads(archive.read('manifest.json'))
            if data.get('schema')!=SCHEMA:raise InputError('지원하지 않는 업무 파일 버전입니다.')
            inputs=data.get('inputs',[])
            if not 1<=len(inputs)<=MAX_FILES:raise InputError('업무 원본 파일 수를 확인해 주세요.')
            expected={'manifest.json'}
            for i,item in enumerate(inputs,1):
                suffix=Path(item['entry']).suffix
                if suffix not in ('.xlsx','.csv','.tsv') or item['entry']!=f'inputs/{i:03d}{suffix}':raise InputError('업무 원본 경로가 올바르지 않습니다.')
                if Path(item['name']).name!=item['name'] or any(s in item['name'] for s in ('/','\\',':')):raise InputError('업무 원본 이름이 올바르지 않습니다.')
                expected.add(item['entry'])
            support_inputs=data.get('supportInputs',[])
            if len(support_inputs)>5:raise InputError('보조자료 첨부 수를 확인해 주세요.')
            for i,item in enumerate(support_inputs,1):
                suffix=Path(item['entry']).suffix
                if suffix not in ('.xlsx','.csv','.tsv') or item['entry']!=f'support/{i:03d}{suffix}' or Path(item['name']).name!=item['name'] or any(s in item['name'] for s in ('/','\\',':')):
                    raise InputError('업무 보조자료 경로가 올바르지 않습니다.')
                expected.add(item['entry'])
            if set(names)!=expected:raise InputError('업무에 예상하지 못한 첨부가 있습니다.')
            from .catalogs import checked_catalog
            checked_catalog(data['catalog'])
            cache=user_data()/'work_cache';cache.mkdir(parents=True,exist_ok=True)
            temporary=tempfile.TemporaryDirectory(prefix='open-',dir=cache);paths=[]
            for i,item in enumerate(inputs,1):
                raw=archive.read(item['entry'])
                if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise InputError('업무에 보관된 원본 해시가 다릅니다.')
                folder=Path(temporary.name)/str(i);folder.mkdir();target=folder/item['name'];target.write_bytes(raw);paths.append(target)
            session=load_batch(paths,data['profile'],data['catalog'],False)
            session.result=normalize(session.raw,data['mappings'],session.catalog,session.profile,session.source,session.history)
            session.mappings=data['mappings'];session.job_path=path;session._restored_temp=temporary
            setup=data.get('supportSetup',{})
            for i,item in enumerate(support_inputs,1):
                raw=archive.read(item['entry'])
                if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise InputError('업무 보조자료 해시가 다릅니다.')
                folder=Path(temporary.name)/('support'+str(i));folder.mkdir();target=folder/item['name'];target.write_bytes(raw)
                setup['tables'][item['table']]['path']=str(target)
            if setup:
                from .support_preparation import prepare_support
                session.support_bundle=prepare_support(setup);session.support_setup=setup;session.support_config=setup['tables']
            session.reviewer=data.get('reviewer','');return session
    except (BadZipFile,KeyError,TypeError,ValueError) as exc:
        if temporary:temporary.cleanup()
        raise InputError('정상 업무 파일인지 확인해 주세요: '+str(exc)) from exc
    except Exception:
        if temporary:temporary.cleanup()
        raise
