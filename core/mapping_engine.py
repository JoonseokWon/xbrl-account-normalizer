from .errors import InputError
from .values import identifier
from .constants import MAPPING_HEADERS
from suggestions import suggest_accounts
from review_history import review_key

def make_mapper(index,mappings,history,profile,catalog,note):
    system=identifier(profile.get("sourceSystem"),"원천시스템")
    discovered={}
    candidate_cache={}
    def mapped(row, kind):
            company = identifier(row.get('company') or profile.get('companyCode'), '회사코드')
            account = identifier(row.get('account'), '원본계정코드')
            name = identifier(row.get('name'), '원본계정명')
            key = kind, company, system, account
            old = discovered.get(key)
            if old and old['원본계정명'] != name:
                raise InputError('같은 회사·시스템·계정코드에 서로 다른 계정명이 있습니다.')
            if key not in discovered:
                discovered[key] = dict(zip(MAPPING_HEADERS, [kind, company, system, account, name, '', '미확정', '']))
            rule = mappings.get(key)
            selected = None
            basis = '미확정'
            history_key = review_key(kind,company,system,account,name,catalog['version'])
            rejected = history.rejected(history_key)
            if rule and rule['상태'] == '거절' and rule['원본계정명'] == name:
                rejected.add(rule['표준계정코드'])
            if rule and rule['상태'] == '확인':
                if rule['원본계정명'] != name:
                    note('ACCOUNT_NAME_CHANGED', '확인한 매핑의 원본계정명과 다릅니다. 매핑을 재확인하세요.', row['_source'], '오류')
                else:
                    selected = index[rule['표준계정코드']]
                    basis = '현재 매핑표 확인'
                    rejected.discard(rule['표준계정코드'])
            elif rule is None:
                accepted = history.accepted(history_key)
                if accepted:
                    previous = index.get(accepted['targetCode'])
                    if previous and (kind != '원장' or previous['kind']=='account'):
                        selected = previous
                        basis = '동일 회사·시스템·계정명·사전 버전의 승인 이력'
                        discovered[key].update({'표준계정코드':previous['code'],'상태':'확인','확인자':accepted['reviewer']})
            candidate_key=(name,kind,tuple(sorted(rejected)),row.get('statement'))
            if candidate_key not in candidate_cache:
                candidate_cache[candidate_key]=suggest_accounts(name,kind,index.values(),rejected,row.get('statement'))
            details=candidate_cache[candidate_key]
            candidates = [item['code'] for item in details]
            if selected is None:
                note('UNMAPPED', '표준계정 매핑 미확정' + (f". 이름 기준 후보: {', '.join(candidates)}" if candidates else ''), row['_source'])
            return {'company':company,'system':system,'originalCode':account,'originalName':name,
                    'standardCode':selected['code'] if selected else None,
                    'standardName':selected['name'] if selected else None,
                    'parentCode':selected.get('parent') if selected else None,
                    'leadCode':selected['lead'] if selected else None,
                    'statement':selected['statement'] if selected else None,
                    'module':selected['module'] if selected else None,
                    'mappingStatus':'확인' if selected else '미확정', 'mappingBasis':basis,
                    'candidates':candidates,'candidateDetails':details,
                    'source':row['_source']}
    return mapped,discovered
