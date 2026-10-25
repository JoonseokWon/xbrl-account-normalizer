"""Explicit field contracts take precedence over configured header aliases."""
from core.errors import InputError

def resolve_fields(headers, role, profile):
    fields = {}
    overrides = profile.get('columnMappings', {}).get(role, {})
    known = set(profile['columns'])
    if set(overrides)-known:
        raise InputError('열 매핑의 표준 필드 이름을 확인하세요: '+', '.join(sorted(set(overrides)-known)))
    for canonical, aliases in profile['columns'].items():
        if canonical in overrides:
            chosen=overrides[canonical]
            if not isinstance(chosen,str) or chosen not in headers:
                raise InputError(f'{role}: 지정한 원본 열을 찾을 수 없습니다: {chosen}')
            fields[canonical]=chosen
            continue
        names = [header for header in aliases if header in headers]
        if len(names)>1:
            raise InputError(f'{role}: {canonical} 열이 여러 개입니다. columnMappings에 원본 열을 지정하세요.')
        if names:
            fields[canonical]=names[0]
    if len(set(fields.values())) != len(fields):
        raise InputError(f'{role}: 하나의 원본 열을 여러 표준 필드에 연결할 수 없습니다.')
    return fields
