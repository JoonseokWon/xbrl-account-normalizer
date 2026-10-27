"""Compile explicit, synthetic definitions into candidate aliases, never approvals."""
from copy import deepcopy
from collections import defaultdict
from core.catalog import catalog_index
from core.errors import InputError
from suggestions import normalized_name


def learn_aliases(catalog, examples):
    result=deepcopy(catalog)
    index=catalog_index(result)
    examples=list(examples)
    blocked={normalized_name(e.get('name')) for e in examples if not e.get('shareable')}
    removed=[]
    for account in index.values():
        for label in list(account.get('aliases',[])):
            if normalized_name(label) in blocked:
                account['aliases'].remove(label);removed.append({'name':label,'target':account['code']})
    labels=defaultdict(set)
    for account in index.values():
        for label in [account['name'],*account.get('aliases',[])]:
            labels[normalized_name(label)].add(account['code'])
    prepared=[]
    for example in examples:
        if example.get('split')!='train':
            raise InputError('학습용으로 분리한 사례만 별칭에 반영할 수 있습니다.')
        if example.get('origin')!='synthetic-definition' or not example.get('definition'):
            raise InputError('더미 계정의 명시된 정의와 출처가 필요합니다.')
        target=example.get('target')
        label=example.get('name')
        if target not in index or index[target]['kind']!='account':
            raise InputError('학습 사례의 상세 표준 계정을 확인해 주세요.')
        if not isinstance(label,str) or not label.strip() or len(label)>200:
            raise InputError('학습 별칭을 확인해 주세요.')
        prepared.append(example)
        if example.get('shareable'):
            labels[normalized_name(label)].add(target)
    added=[];scoped=[]
    for example in prepared:
        label=example['name'];target=example['target']
        if normalized_name(label) in blocked or not example.get('shareable') or labels[normalized_name(label)]!={target}:
            scoped.append(dict(example,reason='회사별 정의 확인 필요 또는 별칭 충돌'))
            continue
        aliases=index[target].setdefault('aliases',[])
        if label not in aliases and label!=index[target]['name']:
            aliases.append(label)
            added.append({'name':label,'target':target,'company':example['company'],
                          'definition':example['definition'],'origin':example['origin']})
    # Catalog version changes invalidate old approvals. Preserve the input version
    # in the report; use the same content-addressed contract as the catalog editor.
    from .catalogs import checked_catalog
    result=checked_catalog(result)
    return result,{'sourceCatalogVersion':catalog['version'],'catalogVersion':result['version'],
                   'method':'정의가 있는 더미 계정의 공통 별칭 누적. 모델 가중치 학습 아님.',
                   'addedAliases':added,'removedAmbiguousAliases':removed,
                   'companyScopedOnly':scoped,'approvalsCreated':0}
