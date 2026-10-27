import hashlib,json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit,unquote
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree as ET
from application.paths import resources
from core.errors import InputError

NS={'xbrli':'http://www.xbrl.org/2003/instance','link':'http://www.xbrl.org/2003/linkbase',
    'xlink':'http://www.w3.org/1999/xlink','iso4217':'http://www.xbrl.org/2003/iso4217',
    'gl-cor':'http://www.xbrl.org/int/gl/cor/2015-03-25','gl-bus':'http://www.xbrl.org/int/gl/bus/2015-03-25'}
ENTITY_SCHEME='urn:account-data-normalizer:company-code'
for prefix,uri in NS.items():ET.register_namespace(prefix,uri)

def q(prefix,name):return '{'+NS[prefix]+'}'+name

def taxonomy_root():return resources()/'vendor/xbrl-gl-2015'

def manifest():return json.loads((taxonomy_root()/'manifest.json').read_text(encoding='utf-8'))

def verify_taxonomy():
    root=taxonomy_root().resolve();info=manifest()
    for entry in info['files']:
        path=(root/entry['file']).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise InputError('포함된 공식 XBRL 스키마의 해시가 다릅니다. 실행팩을 다시 받아 주세요.')
    return info

class OfflineResolver(ET.Resolver):
    def resolve(self,url,pubid,context):
        root=taxonomy_root().resolve();parts=urlsplit(url)
        if Path(url).is_absolute() and parts.scheme not in ('http','https','file'):
            path=Path(url)
        elif parts.scheme in ('http','https'):
            host='www.xbrl.org' if parts.hostname=='xbrl.org' else parts.hostname
            if host not in ('www.xbrl.org','www.w3.org') or parts.query:raise InputError('허용되지 않은 스키마 참조')
            path=root/(host+unquote(parts.path))
        elif parts.scheme=='file':
            text=unquote(parts.path)
            if len(text)>2 and text[0]=='/' and text[2]==':':text=text[1:]
            path=Path(text)
        elif not parts.scheme:path=Path(url)
        else:raise InputError('허용되지 않은 스키마 주소')
        path=path.resolve()
        if not path.is_relative_to(root) or not path.is_file():raise InputError('오프라인 스키마 참조 누락: '+path.name)
        return self.resolve_filename(str(path),context)

@lru_cache(maxsize=1)
def schema():
    parser=ET.XMLParser(resolve_entities=False,no_network=True,load_dtd=False)
    parser.resolvers.add(OfflineResolver())
    root=taxonomy_root();entry=urlsplit(manifest()['entryPoint'])
    return ET.XMLSchema(ET.parse(str(root/(entry.netloc+entry.path)),parser))

def package_taxonomy(path):
    info=verify_taxonomy();root=taxonomy_root()
    names=[entry['file'] for entry in info['files']]+['manifest.json','META-INF/catalog.xml','META-INF/taxonomyPackage.xml','NOTICE.txt']
    with ZipFile(path,'x',ZIP_DEFLATED) as archive:
        for name in names:archive.write(root/name,'xbrl-gl-2015/'+name)
