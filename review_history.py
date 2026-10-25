"""Local, scoped approval/rejection events. No cross-company learned approvals."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import tempfile

def review_key(kind, company, system, source_code, source_name, catalog_version):
    # Exact source names are intentional: renamed accounts require another review.
    return [kind, company, system, source_code, source_name, catalog_version]

class ReviewHistory:
    def __init__(self, events=None):
        self.events = list(events or [])
        self._state = {}
        for event in self.events:
            if event.get('decision') not in ('확인', '거절') or len(event.get('key', [])) != 6:
                raise ValueError('검토 이력 형식이 올바르지 않습니다.')
            state = self._state.setdefault(tuple(event['key']), {'accepted':None,'rejected':set()})
            if event['decision'] == '확인':
                state['accepted'] = event
                state['rejected'].discard(event['targetCode'])
            else:
                state['rejected'].add(event['targetCode'])
                if state['accepted'] and state['accepted']['targetCode'] == event['targetCode']:
                    state['accepted'] = None

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        if payload.get('schema') != 'account-review-history/0.1' or not isinstance(payload.get('events'), list):
            raise ValueError('지원하지 않는 검토 이력 파일입니다.')
        return cls(payload['events'])

    def accepted(self, key):
        return self._state.get(tuple(key), {}).get('accepted')

    def rejected(self, key):
        return set(self._state.get(tuple(key), {}).get('rejected', ()))

    def record(self, key, target, decision, reviewer, source):
        body = {'key':list(key),'targetCode':target,'decision':decision,'reviewer':reviewer}
        signature = hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        # A later confirmation of another target is also a reversal for this key.
        latest = next((e for e in reversed(self.events) if e['key']==list(key)),None)
        if latest and latest.get('signature') == signature:
            return
        event = body | {'signature':signature,'recordedAt':datetime.now(timezone.utc).isoformat(), 'source':source}
        self.events.append(event)
        refreshed = ReviewHistory(self.events)
        self._state = refreshed._state

    def record_current_rules(self, mappings, raw, profile, catalog):
        visible = set()
        for role, kind in (('gl','원장'),('fs','재무제표')):
            for row in raw.get(role, []):
                company = row.get('company') or profile.get('companyCode')
                visible.add(tuple(review_key(kind,company,profile['sourceSystem'],row.get('account'),row.get('name'),catalog['version'])))
        for rule in mappings:
            if rule.get('상태') not in ('확인','거절'):
                continue
            key=review_key(rule['입력종류'],rule['회사코드'],rule['원천시스템'],rule['원본계정코드'],rule['원본계정명'],catalog['version'])
            if tuple(key) in visible:
                self.record(key,rule['표준계정코드'],rule['상태'],rule['확인자'],'현재 엑셀 매핑표')

    def save(self, path):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        descriptor,temporary=tempfile.mkstemp(prefix='.review-',suffix='.json',dir=path.parent)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as handle:
                json.dump({'schema':'account-review-history/0.1','events':self.events},handle,ensure_ascii=False,indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary,path)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
