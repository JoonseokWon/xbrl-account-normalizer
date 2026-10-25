"""Small orchestration facade; legacy public imports remain compatible."""
from core.errors import InputError
from core.constants import MAPPING_HEADERS, UNITS
from core.values import identifier, day, money
from core.catalog import catalog_index, mapping_index
from core.mapping_engine import make_mapper
from core.ledger import normalize_ledger
from core.financial import normalize_financial
from core.aggregation import aggregate_movements
from core.bridge import audit_bridge
from review_history import ReviewHistory
from version import VERSION, VALIDATION_STATUS

def normalize(raw,mapping_rows,catalog,profile,source,history=None):
    if profile.get('currency')!='KRW' or profile.get('ledgerUnit') not in UNITS:
        raise InputError('현재 버전은 KRW와 원/천원/백만원 단위를 지원합니다.')
    system=identifier(profile.get('sourceSystem'),'원천시스템')
    index=catalog_index(catalog)
    mappings=mapping_index(mapping_rows,index)
    history=history or ReviewHistory()
    issues=[]
    def note(code,message,ref,severity='검토'):
        issues.append({'code':code,'message':message,'source':ref,'severity':severity})
    mapped,discovered=make_mapper(index,mappings,history,profile,catalog,note)
    ledger=normalize_ledger(raw.get('gl',[]),profile,mapped,note)
    financial=normalize_financial(raw.get('fs',[]),profile,mapped,note)
    groups=aggregate_movements(ledger)
    # Unused existing rules are retained, preventing cross-company mappings from disappearing.
    mapping_output = list(mapping_rows) + [r for key,r in discovered.items() if key not in mappings]
    errors = sum(row['severity'] == '오류' for row in issues)
    pending = sum(row['mappingStatus'] != '확인' for row in ledger + financial)
    return {'schema':'audit-account-normalization/0.2','version':VERSION,'validationStatus':VALIDATION_STATUS,
            'candidateScoreMeaning':'문자열 유사도이며 정확도·확률이 아닙니다. 후보 점수는 자동 승인에 사용하지 않습니다.',
            'catalogVersion':catalog['version'],
            'source':source,'currency':'KRW','amountUnit':'원','sourceSystem':system,
            'status':'변환오류' if errors else '매핑검토필요' if pending else '계정매핑완료',
            'counts':{'sourceGlRows':len(raw.get('gl',[])),'sourceFsRows':len(raw.get('fs',[])),
                      'normalizedGlRows':len(ledger),'normalizedFsRows':len(financial),
                      'pendingRows':pending,'errors':errors},
            'ledger':ledger,'financial':financial,'movements':groups,'issues':issues,'mappings':mapping_output}
