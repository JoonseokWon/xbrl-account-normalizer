"""Explicit note and fact editing. Values and classifications are never inferred."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from core.errors import InputError
from ._shared import SCHEMA, commit, digest, event_hash, invalidate, now, replay, state_shape, text, validate


def create_workspace(report=None, actor='사용자', notes=None):
    text(actor, '변경 담당자', 2000, False)
    if report is None:
        report = {'schema': 'account-normalizer-filing/1', 'entity': {'name': '', 'identifier': '', 'scheme': ''},
                  'reporting': {'periodStart': '', 'periodEnd': '', 'consolidation': '별도', 'comparativePeriods': []}, 'facts': [], 'inputs': []}
    value = deepcopy(report)
    invalidate(value)
    state = {'report': value, 'notes': deepcopy(notes or []), 'review': {'taxonomyConfirmed': False}}
    state_shape(state)
    workspace = {'schema': SCHEMA, 'workspaceId': uuid4().hex, 'createdAt': now(), 'initialState': deepcopy(state), 'state': deepcopy(state), 'revisions': []}
    entry = {'revision': 1, 'timestamp': workspace['createdAt'], 'actor': actor.strip(), 'action': 'create', 'details': {},
             'previousHash': '0' * 64, 'beforeHash': digest(state), 'afterHash': digest(state), 'changes': []}
    entry['hash'] = event_hash(workspace['workspaceId'], entry)
    workspace['revisions'].append(entry)
    return workspace


def _state(workspace):
    validate(workspace)
    return deepcopy(workspace['state'])


def _edited(workspace, state, actor, action, details=None):
    invalidate(state['report'])
    return commit(workspace, state, actor, action, details)


def add_note(workspace, title, text='', fact_ids=(), actor='사용자'):
    state = _state(workspace)
    state['notes'].append({'id': 'note_' + uuid4().hex, 'title': title, 'text': text, 'factIds': list(fact_ids), 'reviewRequired': True})
    return _edited(workspace, state, actor, 'note-add')


def update_note(workspace, note_id, title=None, text=None, fact_ids=None, actor='사용자'):
    state = _state(workspace)
    note = next((n for n in state['notes'] if n['id'] == note_id), None)
    if note is None:
        raise InputError('수정할 주석이 없어요.')
    if title is not None:
        note['title'] = title
    if text is not None:
        note['text'] = text
    if fact_ids is not None:
        note['factIds'] = list(fact_ids)
    note['reviewRequired'] = True
    return _edited(workspace, state, actor, 'note-edit', {'noteId': note_id})


def delete_note(workspace, note_id, actor='사용자'):
    state = _state(workspace)
    if not any(n['id'] == note_id for n in state['notes']):
        raise InputError('삭제할 주석이 없어요.')
    state['notes'] = [n for n in state['notes'] if n['id'] != note_id]
    return _edited(workspace, state, actor, 'note-delete', {'noteId': note_id})


def upsert_fact(workspace, fact, actor='사용자'):
    state = _state(workspace)
    if not isinstance(fact, dict) or not isinstance(fact.get('id'), str):
        raise InputError('공시 항목 객체와 ID를 입력해 주세요.')
    facts = state['report']['facts']
    found = next((i for i, old in enumerate(facts) if old['id'] == fact['id']), None)
    if found is None:
        facts.append(deepcopy(fact))
    else:
        facts[found] = deepcopy(fact)
    for note in state['notes']:
        if fact['id'] in note['factIds']:
            note['reviewRequired'] = True
    return _edited(workspace, state, actor, 'fact-add' if found is None else 'fact-edit', {'factId': fact['id']})


def remove_fact(workspace, fact_id, actor='사용자'):
    state = _state(workspace)
    if not any(f['id'] == fact_id for f in state['report']['facts']):
        raise InputError('삭제할 공시 항목이 없어요.')
    state['report']['facts'] = [f for f in state['report']['facts'] if f['id'] != fact_id]
    for note in state['notes']:
        if fact_id in note['factIds']:
            note['factIds'].remove(fact_id)
            note['reviewRequired'] = True
    return _edited(workspace, state, actor, 'fact-delete', {'factId': fact_id})


def update_reporting(workspace, entity=None, reporting=None, actor='사용자'):
    state = _state(workspace)
    if entity is not None:
        if not isinstance(entity, dict):
            raise InputError('회사 정보는 객체여야 해요.')
        state['report']['entity'] = deepcopy(entity)
    if reporting is not None:
        if not isinstance(reporting, dict):
            raise InputError('보고 기간 정보는 객체여야 해요.')
        state['report']['reporting'] = deepcopy(reporting)
    state['review']['taxonomyConfirmed'] = False
    return _edited(workspace, state, actor, 'reporting-edit')


def confirm_taxonomy(workspace, fingerprint, actor='사용자'):
    text(fingerprint, '택사노미 식별값', 2000, False)
    state = _state(workspace)
    state['report']['taxonomyFingerprint'] = fingerprint
    state['review']['taxonomyConfirmed'] = True
    # This only records selection. Individual fact approvals still belong to the filing workflow.
    return _edited(workspace, state, actor, 'taxonomy-select', {'fingerprint': fingerprint})


def list_revisions(workspace):
    validate(workspace)
    return [{k: deepcopy(entry[k]) for k in ('revision', 'timestamp', 'actor', 'action', 'details', 'beforeHash', 'afterHash', 'hash')}
            | {'changeCount': len(entry['changes'])} for entry in workspace['revisions']]


def revision_state(workspace, revision):
    validate(workspace)
    if type(revision) is not int or not 1 <= revision <= len(workspace['revisions']):
        raise InputError('조회할 변경 이력 번호를 확인해 주세요.')
    state = deepcopy(workspace['initialState'])
    for entry in workspace['revisions'][:revision]:
        state = replay(state, entry['changes'])
    return state


def restore_revision(workspace, revision, actor='사용자'):
    state = revision_state(workspace, revision)
    state['review']['taxonomyConfirmed'] = False
    for note in state['notes']:
        note['reviewRequired'] = True
    return _edited(workspace, state, actor, 'revision-restore', {'restoredRevision': revision})


def filing_report(workspace, catalog=None):
    """Return a draft, or an explicitly approved report checked by the filing model.

    Free note prose is work metadata; it is never silently turned into a taxonomy fact.
    """
    validate(workspace)
    result = deepcopy(workspace['state']['report'])
    result['disclosureNotes'] = deepcopy(workspace['state']['notes'])
    result['disclosureWorkspace'] = {'workspaceId': workspace['workspaceId'], 'revision': len(workspace['revisions']),
        'stateHash': digest(workspace['state']), 'notesAreDraftMetadata': True,
        'notice': '주석 서술은 업무 메타데이터입니다. 공식 XML에 포함할 내용은 NOTE 팩트로 명시하고 공시 화면에서 개념·문맥·값을 검토하세요.'}
    if catalog is not None:
        from application.filing import verify_sources
        from xbrl_filing.model import prepare_report
        if not workspace['state']['review']['taxonomyConfirmed'] or result.get('taxonomyFingerprint') != catalog.get('fingerprint'):
            raise InputError('현재 택사노미를 다시 선택하고 공시 항목을 검토해 주세요.')
        # All edits invalidate approval; production export must re-approve via the existing filing workflow.
        verify_sources(result)
        return prepare_report(result, catalog)
    invalidate(result)
    return result


def export_report(workspace, path, catalog=None):
    from .storage import write_json
    target = Path(path)
    if target.suffix.lower() != '.json':
        raise InputError('공시 입력 JSON 확장자는 .json을 사용해 주세요.')
    return write_json(target, filing_report(workspace, catalog))
