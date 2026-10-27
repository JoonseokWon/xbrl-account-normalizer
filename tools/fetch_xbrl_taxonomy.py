"""Vendor original, pinned XBRL GL COR+BUS schemas and their offline dependencies."""
import hashlib,json,sys
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urldefrag
from urllib.request import Request,urlopen
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'vendor/xbrl-gl-2015'
ENTRY='https://www.xbrl.org/taxonomy/int/gl/2015-03-25/plt/case-c-b/gl-plt-all-2015-03-25.xsd'
XS='{http://www.w3.org/2001/XMLSchema}'
XLINK='{http://www.w3.org/1999/xlink}'

def canonical(url):
    url=urldefrag(url)[0];parts=urlsplit(url)
    if parts.hostname not in ('www.xbrl.org','xbrl.org','www.w3.org') or parts.query:
        raise ValueError('공식 스키마 호스트 이외의 주소: '+url)
    host='www.xbrl.org' if parts.hostname=='xbrl.org' else parts.hostname
    return 'https://'+host+parts.path

def main():
    TARGET.mkdir(parents=True,exist_ok=True);queue=[ENTRY];seen=set();files=[]
    while queue:
        url=canonical(queue.pop(0))
        if url in seen:continue
        seen.add(url)
        if len(seen)>100:raise ValueError('예상한 스키마 파일 수 초과')
        parts=urlsplit(url);relative=parts.netloc+parts.path;path=(TARGET/relative).resolve()
        if not path.is_relative_to(TARGET.resolve()):raise ValueError('스키마 경로 오류')
        if path.exists():data=path.read_bytes()
        else:
            with urlopen(Request(url,headers={'User-Agent':'AccountDataNormalizer schema bundler'}),timeout=45) as response:data=response.read(8*1024**2+1)
            if len(data)>8*1024**2:raise ValueError('스키마 크기 초과')
            ET.fromstring(data);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        tree=ET.fromstring(data)
        for element in tree.iter():
            value=element.get('schemaLocation') if element.tag in (XS+'import',XS+'include',XS+'redefine') else element.get(XLINK+'href')
            if value and urlsplit(urldefrag(value)[0]).path.endswith(('.xsd','.xml')):queue.append(urljoin(url,value))
        files.append({'file':relative,'source':url,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        print(relative,flush=True)
    manifest={'entryPoint':ENTRY.replace('https:','http:'),'version':'2015-03-25','modules':['COR','BUS'],
              'source':'https://specifications.xbrl.org/work-product-index-xbrl-gl-xbrl-gl-2015.html',
              'originalFilesUnmodified':True,'files':sorted(files,key=lambda item:item['file'])}
    (TARGET/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    meta=TARGET/'META-INF';meta.mkdir(exist_ok=True)
    (meta/'catalog.xml').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <rewriteURI uriStartString="http://www.xbrl.org/" rewritePrefix="../www.xbrl.org/"/>
  <rewriteURI uriStartString="https://www.xbrl.org/" rewritePrefix="../www.xbrl.org/"/>
  <rewriteURI uriStartString="http://xbrl.org/" rewritePrefix="../www.xbrl.org/"/>
  <rewriteURI uriStartString="https://xbrl.org/" rewritePrefix="../www.xbrl.org/"/>
  <rewriteURI uriStartString="http://www.w3.org/" rewritePrefix="../www.w3.org/"/>
  <rewriteURI uriStartString="https://www.w3.org/" rewritePrefix="../www.w3.org/"/>
</catalog>\n''',encoding='utf-8')
    (meta/'taxonomyPackage.xml').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<taxonomyPackage xmlns="http://xbrl.org/2016/taxonomy-package" xml:lang="en">
 <identifier>urn:account-data-normalizer:xbrl-gl-2015:cor-bus</identifier>
 <name>XBRL GL 2015 COR+BUS offline bundle</name>
 <description>Unmodified official schemas and linkbases, assembled for offline use by AccountDataNormalizer. This packaging is not an XBRL International certification.</description>
 <version>2015-03-25</version>
 <publisher>AccountDataNormalizer project</publisher>
 <entryPoints><entryPoint><name>XBRL GL 2015 COR+BUS</name>
 <entryPointDocument href="http://www.xbrl.org/taxonomy/int/gl/2015-03-25/plt/case-c-b/gl-plt-all-2015-03-25.xsd"/>
 </entryPoint></entryPoints>
</taxonomyPackage>\n''',encoding='utf-8')
    print(json.dumps({'files':len(files),'bytes':sum(f['bytes'] for f in files)}))

if __name__=='__main__':main()
