"""Explainable name candidates. A score never grants mapping approval."""
from difflib import SequenceMatcher
import re
import unicodedata

def normalized_name(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ''.join(ch for ch in text if ch.isalnum())

def suggest_accounts(name, kind, accounts, rejected=(), statement=None, limit=3, minimum=0.55):
    source = normalized_name(name)
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
    return candidates[:limit]
