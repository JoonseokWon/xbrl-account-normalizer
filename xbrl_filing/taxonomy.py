"""Read a user-provided DTS and validate facts using offline, isolated Arelle.

No IFRS/DART taxonomy is downloaded or redistributed by this module. Package
files are bound to a selected local entry point by content hashes.
"""
from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit, unquote, urldefrag
from urllib.request import url2pathname

from lxml import etree as ET
from core.errors import InputError
from .model import STANDARD_NAMESPACES, _ncname

MAX_FILES = 5_000
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024
XML_SUFFIXES = {'.xsd', '.xml', '.xbrl', '.linkbase'}
CATALOG_NS = 'urn:oasis:names:tc:entity:xmlns:xml:catalog'


def load_taxonomy(entry_path):
    from .runtime import run_worker
    return run_worker('catalog', {'entry': str(Path(entry_path).resolve())})


def validate_instance(path, catalog):
    from .runtime import run_worker
    if not isinstance(catalog, dict):
        raise InputError('택사노미를 먼저 가져와 주세요.')
    reference = {key: catalog.get(key) for key in ('entryPoint', 'root', 'fingerprint', 'packageManifestPath')}
    return run_worker('validate', {'path': str(Path(path).resolve()), 'catalog': reference})


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(1024 * 1024):digest.update(data)
    return digest.hexdigest()


def _safe_xml(path):
    if path.stat().st_size > MAX_XML_BYTES:
        raise InputError('택사노미 또는 XML 파일이 64MB 한도를 넘습니다.')
    try:
        tree = ET.parse(str(path), ET.XMLParser(load_dtd=False, resolve_entities=False, no_network=True, huge_tree=False))
    except (ET.XMLSyntaxError, OSError) as exc:
        raise InputError('XML 파일 구문을 확인해 주세요: ' + path.name) from exc
    if tree.docinfo.doctype:
        known_catalog = (path.name == 'catalog.xml' and tree.getroot().tag == '{'+CATALOG_NS+'}catalog'
                         and tree.docinfo.public_id == '-//OASIS//DTD Entity Resolution XML Catalog V1.0//EN'
                         and tree.docinfo.system_url == 'http://www.oasis-open.org/committees/entity/release/1.0/catalog.dtd')
        if not known_catalog:
            raise InputError('DTD가 있는 XML은 읽지 않습니다: ' + path.name)
    if tree.docinfo.internalDTD is not None and list(tree.docinfo.internalDTD.iterentities()):
        raise InputError('XML 엔티티 선언은 읽지 않습니다: ' + path.name)
    if any(isinstance(node, ET._Entity) for node in tree.iter()):
        raise InputError('XML 엔티티는 읽지 않습니다: ' + path.name)
    return tree


def _root_for(entry):
    for ancestor in [entry.parent, *list(entry.parents)[1:8]]:
        candidate = ancestor/'META-INF/taxonomyPackage.xml'
        if candidate.is_file():return ancestor, candidate
    # The official Windows writer stores a host/path cache without META-INF.
    # Keep its whole selected cache bound to the snapshot; do not edit it.
    if re.fullmatch(r'dart_all_\d{4}-\d{2}-\d{2}\.xsd',entry.name):
        for ancestor in list(entry.parents)[:8]:
            if ancestor.name.casefold()=='taxonomycache' and entry.relative_to(ancestor).parts[0].casefold()=='dart.fss.or.kr':
                return ancestor,None
    return entry.parent, None


def _snapshot(entry_path):
    if not isinstance(entry_path, (str, Path)):
        raise InputError('로컬 택사노미 XSD 진입점을 선택해 주세요.')
    entry = Path(entry_path).resolve()
    if not entry.is_file() or entry.suffix.lower() != '.xsd':
        raise InputError('존재하는 로컬 XSD 진입점이 필요합니다.')
    root, manifest = _root_for(entry)
    if root == Path(root.anchor):
        raise InputError('드라이브 최상위 대신 택사노미 전용 폴더를 사용해 주세요.')
    files = [];total = 0
    paths=_cache_dependencies(entry,root) if root.name.casefold()=='taxonomycache' else sorted(root.rglob('*'))
    for path in paths:
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise InputError('택사노미 폴더의 심볼릭 링크·정션은 지원하지 않습니다.')
        if not path.is_file():continue
        if not path.resolve().is_relative_to(root):
            raise InputError('택사노미 폴더 밖 파일을 참조할 수 없습니다.')
        total += path.stat().st_size
        if len(files) >= MAX_FILES or total > MAX_PACKAGE_BYTES:
            raise InputError('택사노미 폴더는 5,000파일·256MB 이내여야 합니다.')
        if path.suffix.lower() in XML_SUFFIXES:_safe_xml(path)
        before = path.stat();sha = _digest(path);after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise InputError('읽는 중 택사노미 파일이 변경되었습니다.')
        files.append({'file': path.relative_to(root).as_posix(), 'sha256': sha, 'bytes': after.st_size})
    identity = {'entry': entry.relative_to(root).as_posix(), 'files': files}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'entryPoint': str(entry), 'root': str(root), 'files': files, 'fingerprint': fingerprint,
            'packageManifestPath': str(manifest) if manifest else None}


def _cache_dependencies(entry,root):
    """Bind only the selected DTS closure in a cache containing many releases."""
    pending=[entry];known={entry};result=[];total=0;reference_seen=set()
    while pending:
        path=pending.pop();total+=path.stat().st_size
        if len(result)>=MAX_FILES or total>MAX_PACKAGE_BYTES:
            raise InputError('선택한 택사노미 의존 파일은 5,000개·256MB 이내여야 합니다.')
        tree=_safe_xml(path);result.append(path)
        for node in tree.iter():
            if not isinstance(node.tag,str):continue
            references=[]
            if node.get('schemaLocation'):references.append(node.get('schemaLocation'))
            if node.get('{http://www.w3.org/1999/xlink}href'):references.append(node.get('{http://www.w3.org/1999/xlink}href'))
            schema_locations=node.get('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation')
            if schema_locations:references.extend(schema_locations.split()[1::2])
            for reference in references:
                uri=urlsplit(reference)
                # Linkbases repeat the same schema for thousands of concept
                # fragments. Resolve each physical reference only once.
                key=(uri.scheme,uri.netloc,uri.path,str(path.parent) if not uri.scheme else '')
                if key in reference_seen:continue
                reference_seen.add(key)
                if uri.scheme in ('http','https'):
                    if not uri.hostname:raise InputError('택사노미 참조 URI를 확인해 주세요.')
                    candidate=root/uri.hostname/unquote(uri.path.lstrip('/'))
                elif uri.scheme=='file':candidate=Path(_canonical_local_uri(urldefrag(reference)[0]))
                elif uri.scheme:continue
                else:candidate=path.parent/unquote(uri.path) if uri.path else path
                if candidate.is_symlink() or (hasattr(candidate,'is_junction') and candidate.is_junction()):
                    raise InputError('택사노미 의존 파일의 심볼릭 링크·정션은 지원하지 않습니다.')
                candidate=candidate.resolve()
                if not candidate.is_relative_to(root):raise InputError('택사노미 의존 참조가 캐시 폴더 밖에 있습니다.')
                if not candidate.is_file() or candidate in known:continue
                known.add(candidate)
                if len(known)>MAX_FILES:raise InputError('택사노미 의존 파일 수 한도를 넘었습니다.')
                pending.append(candidate)
    return sorted(result)


def _catalog_rules(snapshot):
    root = Path(snapshot['root']);path = root/'META-INF/catalog.xml'
    if not path.is_file():
        if root.name.casefold()=='taxonomycache':
            rules=[]
            for host in sorted(root.iterdir()):
                if host.is_dir() and re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?',host.name):
                    for scheme in ('http','https'):rules.append((scheme+'://'+host.name+'/',host.resolve()))
            return rules
        return []
    rules = []
    for node in _safe_xml(path).getroot().iter():
        local = ET.QName(node).localname if isinstance(node.tag, str) else ''
        if not local or local in ('catalog', 'group'):continue
        if local != 'rewriteURI':
            raise InputError('로컬 rewriteURI 방식의 택사노미 catalog만 지원합니다.')
        start = node.get('uriStartString');relative = node.get('rewritePrefix')
        if not start or not relative or urlsplit(start).scheme not in ('http', 'https'):
            raise InputError('택사노미 catalog의 URI 연결을 확인해 주세요.')
        target = (path.parent/relative).resolve()
        if not target.is_relative_to(root):
            raise InputError('택사노미 catalog가 폴더 밖을 참조합니다.')
        rules.append((start, target))
    return rules


def _schema_ref(snapshot, rules):
    entry = Path(snapshot['entryPoint'])
    for prefix, target in sorted(rules, key=lambda rule: len(str(rule[1])), reverse=True):
        if entry.is_relative_to(target):return prefix.rstrip('/')+'/'+entry.relative_to(target).as_posix()
    return entry.as_uri()


def _canonical_local_uri(value):
    if not isinstance(value, str) or value.startswith(('http://', 'https://', 'urn:')):return value
    original = value
    if value.startswith('file:'):
        parts = urlsplit(value)
        if parts.netloc not in ('', 'localhost'):raise InputError('원격 파일 URI는 지원하지 않습니다.')
        value = url2pathname(parts.path)
        if parts.fragment:value += '#'+parts.fragment
    value, fragment = urldefrag(value)
    if os.name == 'nt' and re.match(r'^[\\/][A-Za-z]:[\\/]', value):value = value[1:]
    path = Path(value)
    if not path.exists():
        decoded = Path(unquote(value))
        if decoded.exists():path = decoded
    if path.is_absolute():return str(path.resolve())+('#'+fragment if fragment else '')
    return original


@contextmanager
def _controller(snapshot, instance=None):
    from arelle import Cntlr
    from arelle.ModelFormulaObject import FormulaOptions
    from arelle.ValidateXbrlCalcs import ValidateCalcsMode
    rules = _catalog_rules(snapshot)
    with tempfile.TemporaryDirectory(prefix='account-filing-cache-') as temporary:
        controller = Cntlr.Cntlr(logFileName='logToBuffer', disable_persistent_config=True)
        try:
            controller.webCache.workOffline = True
            controller.webCache.cacheDir = str(Path(temporary)/'cache')
            controller.modelManager.validateDisclosureSystem = False
            # Run calculation generators separately so absent contributing
            # facts are recorded as skipped instead of being treated as zero.
            controller.modelManager.validateCalcs = ValidateCalcsMode.NONE
            controller.modelManager.formulaOptions = FormulaOptions()
            controller.modelManager.formulaOptions.formulaAction = 'none'
            built_in = Path(controller.webCache.builtInCacheDir).resolve()
            root = Path(snapshot['root'])
            instance = Path(instance).resolve() if instance is not None else None
            original_getfilename = controller.webCache.getfilename
            original_normalize = controller.webCache.normalizeUrl
            def normalize_url(url, base=None):
                return _canonical_local_uri(original_normalize(url, base))
            controller.webCache.normalizeUrl = normalize_url
            checked = set()
            def getfilename(*args, **kwargs):
                url = args[0] if args else kwargs.get('url')
                base = args[1] if len(args) > 1 else kwargs.get('base')
                normalized = controller.webCache.normalizeUrl(url, base) if url is not None and (base is not None or kwargs.get('normalize')) else url
                result = None
                if normalized:
                    for prefix, target in sorted(rules, key=lambda rule: len(rule[0]), reverse=True):
                        if normalized.startswith(prefix):
                            mapped = (target/unquote(normalized[len(prefix):])).resolve()
                            if not mapped.is_relative_to(root):raise InputError('택사노미 URI가 폴더 밖을 참조합니다.')
                            result = str(mapped);break
                    if result is None and normalized.startswith('file:'):
                        parts = urlsplit(normalized)
                        if parts.netloc not in ('', 'localhost'):raise InputError('원격 파일 URI는 지원하지 않습니다.')
                        result = url2pathname(parts.path)
                if result is None:result = original_getfilename(*args, **kwargs)
                if result:
                    # Arelle normalizes some file:///C:/... references into
                    # \C:\... with URI-escaped spaces. Decode only when the
                    # original local filename does not exist, retaining literal
                    # percent characters in real selected filenames.
                    result = _canonical_local_uri(str(result))
                    path = Path(result).resolve()
                    if not (path.is_relative_to(root) or path.is_relative_to(built_in) or path == instance):
                        raise InputError('선택한 택사노미·내장 표준 스키마 밖의 참조를 차단했습니다: ' + str(result)[:2000])
                    if path.is_file() and path not in checked:
                        _safe_xml(path);checked.add(path)
                    return str(path)
                return result
            controller.webCache.getfilename = getfilename
            # Expanded packages are read directly. Arelle's ZIP package validator
            # would reject a standalone manifest, so apply its checked OASIS URI
            # rewrites here without copying or repackaging licensed taxonomies.
            yield controller, rules
        finally:
            controller.modelManager.close()
            controller.close()


def _logs(controller):
    value = json.loads(controller.logHandler.getJson())
    return value.get('log', []) if isinstance(value, dict) else []


def _messages(logs):
    errors = [];warnings = []
    for entry in logs:
        code = str(entry.get('code', ''))
        level = str(entry.get('level', '')).lower()
        message = entry.get('message', {})
        text = message.get('text', '') if isinstance(message, dict) else str(message)
        refs = entry.get('refs') or []
        first = refs[0] if refs and isinstance(refs[0], dict) else {}
        item = {'code': code, 'message': text, 'file': first.get('href', ''), 'line': first.get('sourceLine')}
        if level in ('error', 'critical', 'fatal', 'inconsistency') or 'inconsistency' in code.lower() or 'inconsistent' in code.lower() or code.startswith('exception:'):
            errors.append(item)
        elif level in ('warning', 'inconsistency'):
            warnings.append(item)
    return errors, warnings


def _metadata(model, snapshot, rules):
    from arelle import XbrlConst
    namespaces = dict(STANDARD_NAMESPACES);by_uri = {uri: prefix for prefix, uri in namespaces.items()}
    def add_namespace(uri, preferred=None):
        if not uri:return None
        if uri in by_uri:return by_uri[uri]
        prefix = preferred if _ncname(preferred) and not preferred.lower().startswith('xml') and preferred not in namespaces else None
        if not prefix:
            number = 1
            while 'ns'+str(number) in namespaces:number += 1
            prefix = 'ns'+str(number)
        namespaces[prefix] = uri;by_uri[uri] = prefix
        return prefix
    for prefix, uri in sorted(model.prefixedNamespaces.items(), key=lambda item: str(item[0])):
        if uri != 'http://www.w3.org/XML/1998/namespace':add_namespace(uri, prefix)
    def name(qname):
        if qname is None:return ''
        return add_namespace(qname.namespaceURI, qname.prefix)+':'+qname.localName if qname.namespaceURI else qname.localName
    concepts = {}
    for qname, concept in model.qnameConcepts.items():
        if not (concept.isItem or concept.isDimensionItem or concept.isHypercubeItem):continue
        key = name(qname);base = concept.baseXbrliType or '';xsd = concept.baseXsdType
        if concept.isMonetary:kind = 'monetary'
        elif concept.isShares:kind = 'shares'
        elif base == 'perShareItemType':kind = 'perShare'
        elif concept.isNumeric:kind = 'decimal'
        elif xsd in ('string', 'normalizedString', 'token', 'anyURI', 'language'):kind = 'string'
        elif xsd == 'boolean':kind = 'boolean'
        elif xsd == 'date':kind = 'date'
        else:kind = 'unsupported'
        label = concept.label(lang=('ko', 'en'), fallbackToQname=False, strip=True) or qname.localName
        concepts[key] = {'label': label, 'namespace': qname.namespaceURI, 'localName': qname.localName,
                         'periodType': concept.periodType, 'abstract': bool(concept.isAbstract),
                         'type': name(concept.typeQname), 'numeric': bool(concept.isNumeric), 'kind': kind,
                         'substitutionGroup': name(concept.substitutionGroupQname), 'typedDomainRef': concept.typedDomainRef,
                         'balance': concept.balance}
    if not concepts:raise InputError('택사노미 진입점에서 보고 개념을 찾지 못했습니다.')
    relationship_counts = {'presentation': len(model.relationshipSet(XbrlConst.parentChild).modelRelationships),
                           'calculation10': len(model.relationshipSet(XbrlConst.summationItem).modelRelationships),
                           'calculation11': len(model.relationshipSet(XbrlConst.summationItem11).modelRelationships)}
    return dict(snapshot, namespaces=namespaces, concepts=concepts, schemaRef=_schema_ref(snapshot, rules),
                validator='Arelle', validatorVersion=version('arelle-release'), relationshipCounts=relationship_counts)


def _assert_stable(snapshot):
    current = _snapshot(snapshot['entryPoint'])
    if current['fingerprint'] != snapshot['fingerprint'] or current['root'] != snapshot['root']:
        raise InputError('가져온 뒤 택사노미 파일이 변경되었습니다. 다시 가져와 주세요.')


def _load_taxonomy(entry_path):
    snapshot = _snapshot(entry_path)
    with _controller(snapshot) as (controller, rules):
        cache_metadata=Path(snapshot['root']).name.casefold()=='taxonomycache'
        if cache_metadata:
            # Search/type metadata does not need the writer's very large role
            # graphs. Validation uses a fresh controller and loads them all.
            controller.modelManager.skipLoading=re.compile(r'.*_(?:def|pre|cal|ref)\.xml$',re.IGNORECASE)
        model = controller.modelManager.load(snapshot['entryPoint'])
        errors, warnings = _messages(_logs(controller))
        if model.modelDocument is None or errors or model.errors:
            detail = errors[0]['message'] if errors else '누락된 스키마·링크베이스를 확인해 주세요.'
            raise InputError('택사노미를 완전히 읽지 못했습니다: '+detail)
        result = _metadata(model, snapshot, rules)
        result['warnings'] = warnings
        if cache_metadata:result['catalogScope']='concepts-and-types; relationship validation only at export'
        _assert_stable(snapshot)
        return result


def _calculation_coverage(model):
    from arelle import XbrlConst
    groups = {}
    for arcrole in (XbrlConst.summationItem, XbrlConst.summationItem11):
        for relationship in model.relationshipSet(arcrole).modelRelationships:
            if relationship.fromModelObject is None or relationship.toModelObject is None:continue
            key = (arcrole, relationship.linkrole, relationship.fromModelObject.qname)
            groups.setdefault(key, set()).add(relationship.toModelObject.qname)
    available = {}
    for fact in model.factsInInstance:
        if fact.isNumeric and not fact.isNil and fact.context is not None and fact.unit is not None:
            available.setdefault(fact.qname, set()).add((fact.context.contextDimAwareHash, fact.unit.hash))
    complete = incomplete = 0
    for (_, _, parent), children in groups.items():
        for key in available.get(parent, set()):
            if all(key in available.get(child, set()) for child in children):complete += 1
            else:incomplete += 1
    return {'networks': len(groups), 'completeBindings': complete, 'incompleteBindings': incomplete}


def _incomplete_calculation(model, arguments):
    from arelle import XbrlConst
    missing = arguments.get('unreportedContributors')
    if missing and missing != 'none':return True
    context = model.contexts.get(arguments.get('contextID'))
    unit = model.units.get(arguments.get('unitID'))
    concept = model.qnameConcepts.get(arguments.get('concept'))
    if context is None or unit is None or concept is None:return False
    matched = []
    for arcrole in (XbrlConst.summationItem, XbrlConst.summationItem11):
        relationships = model.relationshipSet(arcrole, arguments.get('linkrole')).fromModelObject(concept)
        if not relationships:continue
        complete = True
        for relationship in relationships:
            child = relationship.toModelObject
            facts = model.factsByQname.get(child.qname, []) if child is not None else []
            if not any(not f.isNil and f.context is not None and f.unit is not None
                       and f.context.isEqualTo(context) and f.unit.isEqualTo(unit) for f in facts):
                complete = False;break
        matched.append(complete)
    return bool(matched) and not any(matched)


def _validate_instance(instance_path, catalog):
    from arelle import Validate, ValidateXbrlCalcs, XbrlConst
    from arelle.ValidateXbrlCalcs import ValidateCalcsMode
    from arelle.ModelDocument import Type
    if not isinstance(catalog, dict) or not isinstance(catalog.get('fingerprint'), str):
        raise InputError('택사노미 가져오기 기록이 필요합니다.')
    snapshot = _snapshot(catalog.get('entryPoint'))
    if snapshot['fingerprint'] != catalog['fingerprint'] or snapshot['root'] != catalog.get('root'):
        raise InputError('가져온 뒤 택사노미 또는 진입점이 변경되었습니다.')
    instance = Path(instance_path).resolve()
    if not instance.is_file():raise InputError('검사할 XBRL 파일이 없습니다.')
    tree = _safe_xml(instance)
    if tree.getroot().tag != '{'+STANDARD_NAMESPACES['xbrli']+'}xbrl':
        raise InputError('XBRL 2.1 인스턴스 파일이 필요합니다.')
    before = _digest(instance)
    with _controller(snapshot, instance) as (controller, _):
        model = controller.modelManager.load(str(instance))
        if model.modelDocument is None or model.modelDocument.type != Type.INSTANCE:
            raise InputError('XBRL 인스턴스를 완전히 읽지 못했습니다.')
        Validate.validate(model)
        modes = []
        if model.relationshipSet(XbrlConst.summationItem).modelRelationships:modes.append(ValidateCalcsMode.XBRL_v2_1)
        if model.relationshipSet(XbrlConst.summationItem11).modelRelationships:modes.append(ValidateCalcsMode.ROUND_TO_NEAREST)
        for mode in modes:
            for result in ValidateXbrlCalcs.validate(model, mode):
                if _incomplete_calculation(model, result.args):continue
                controller.validation(result, fileSource=model.fileSource)
        errors, warnings = _messages(_logs(controller))
        known = {item['code'] for item in errors}
        for code in model.errors:
            if isinstance(code, str) and code not in known:
                errors.append({'code': code, 'message': 'Arelle가 보고한 XBRL 검사 오류입니다.', 'file': instance.name, 'line': None})
        coverage = _calculation_coverage(model)
        passed = not errors
        calculation_error = any('calc' in item['code'].lower() for item in errors)
        checks = [{'code': 'XBRL_21_DTS', 'status': 'pass' if passed else 'error',
                   'message': 'Arelle의 XBRL 2.1·팩트 자료형·기간·차원 검사를 수행했습니다.'},
                  {'code': 'CALCULATION_COMPLETE_BINDINGS', 'status': 'error' if calculation_error else 'pass' if coverage['completeBindings'] and passed else 'skipped',
                   'message': f"계산망 완전 연결 {coverage['completeBindings']}건. 필요한 하위 팩트가 모두 있는 경우만 계산 검사합니다."},
                  {'code': 'CALCULATION_MISSING_FACTS', 'status': 'skipped',
                   'message': f"하위 팩트가 없는 계산 연결 {coverage['incompleteBindings']}건은 합계 일치를 확인한 것이 아닙니다."},
                  {'code': 'FORMULA', 'status': 'skipped', 'message': 'Formula·회사별 주석 완전성·공시 접수 규칙은 이 검사에 포함하지 않습니다.'},
                  {'code': 'DART_ACCEPTANCE', 'status': 'skipped', 'message': 'DART 편집기 가져오기·최종 접수 검증은 별도 확인이 필요합니다.'}]
        _assert_stable(snapshot)
        if _digest(instance) != before:raise InputError('검사하는 중 XBRL 파일이 변경되었습니다.')
        return {'passed': passed, 'errors': errors, 'warnings': warnings, 'checks': checks,
                'validator': 'Arelle', 'version': version('arelle-release'), 'offline': True,
                'calculationCoverage': coverage, 'taxonomyFingerprint': snapshot['fingerprint']}
