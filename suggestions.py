"""Explainable name candidates. A score never grants mapping approval."""
from difflib import SequenceMatcher
import re
import unicodedata

def normalized_name(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ''.join(ch for ch in text if ch.isalnum())

def label_without_metadata(value):
    """Remove only fixed organizational annotations, never accounting qualifiers."""
    text=unicodedata.normalize('NFKC',str(value or '')).strip()
    text=re.sub(r'^관리부\s*/\s*','',text)
    text=re.sub(r'\s*-\s*국내사업$','',text)
    text=re.sub(r'\s*(?:\((?:본점|관리계정)\)|\[(?:본점|관리계정)\])\s*$','',text)
    return normalized_name(text)

def suggest_accounts(name, kind, accounts, rejected=(), statement=None, limit=3, minimum=0.55):
    source = normalized_name(name)
    without_metadata=label_without_metadata(name)
    if not source:
        return []
    rejected = set(rejected)
    candidates = []
    for account in accounts:
        if account['code'] in rejected:
            continue
        if kind == '원장' and account['kind'] != 'account':
            continue
        if statement in ('BS', 'PL') and account['statement'] != statement:
            continue
        labels = [account['name'], *account.get('aliases', [])]
        best = None
        for label in labels:
            target = normalized_name(label)
            if not target:
                continue
            if str(name) == label:
                score, reason = 1.0, '계정명 또는 사전 별칭 일치'
            elif source == target:
                score, reason = 0.99, '공백·구두점·대소문자 정규화 후 일치'
            elif without_metadata==target:
                score, reason = 0.97, '본점·관리부 등 조직 표기 제거 후 사전 별칭 일치'
            else:
                score = SequenceMatcher(None, source, target, autojunk=False).ratio()
                reason = '문자열 유사도'
            candidate = {'code':account['code'],'name':account['name'],
                         'score':round(score, 4),'reason':reason,'matchedLabel':label}
            if best is None or candidate['score'] > best['score']:
                best = candidate
        if best and best['score'] >= minimum:
            candidates.append(best)
    candidates.sort(key=lambda item:(-item['score'], item['code']))
    if without_metadata in {'정산계정','예치금','수수료','선급'}:
        for item in candidates:
            item['requiresDefinition']=True
            item['reason']+=' · 회사별 의미가 달라 계정 정의 확인 필요'
    if candidates and sum(item['score']==candidates[0]['score'] for item in candidates)>1:
        for item in candidates:
            if item['score']==candidates[0]['score']:
                item['reason']+=' · 동점 후보가 있어 계정 정의 확인 필요'
    return candidates[:limit]
