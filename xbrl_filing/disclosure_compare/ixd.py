"""Read the declared instance only after existing IXD package inspection."""
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from ..official_writer.artifacts import inspect_artifact, _safe_name
from ..official_writer.reconcile import _parse_instance, _summary, MAX_INSTANCE_BYTES


def _human_date(value, end=False):
    parsed = datetime.fromisoformat(value)
    # Date-only XBRL end/instant is internally represented as next midnight.
    # Preserve non-midnight/timezone times exactly instead of dropping precision.
    if parsed.tzinfo is None and parsed.time().isoformat() == '00:00:00':
        if end:
            parsed -= timedelta(days=1)
        return parsed.date().isoformat()
    return value


def read_ixd(path):
    source = Path(path)
    inspection = inspect_artifact(source)
    if inspection.get('kind') != 'submission-candidate' or inspection.get('errors'):
        raise ValueError('제출용 IXD 패키지 구조를 확인하지 못했습니다. ' + ' '.join(inspection.get('errors', [])))
    member = inspection['metadata']['references']['INSTANCE']
    with ZipFile(source) as archive:
        index = {_safe_name(info.orig_filename).casefold(): info for info in archive.infolist()}
        entry = index[member.casefold()]
        if entry.file_size > MAX_INSTANCE_BYTES:
            raise ValueError('IXD 인스턴스 XML 크기 한도를 넘었습니다.')
        prepared = _parse_instance(archive.open(entry))
    facts = []
    for item in prepared:
        fact = _summary(item)
        period = item['key'][2]
        if period[0] == 'instant':
            fact['period'] = {'kind': 'instant', 'instant': _human_date(period[1], end=True)}
        elif period[0] == 'duration':
            fact['period'] = {'kind': 'duration', 'start': _human_date(period[1]),
                              'end': _human_date(period[2], end=True)}
        else:
            fact['period'] = {'kind': 'forever'}
        fact['dimensions'] = [{'placement': p, 'axis': a, 'member': m}
                              for p, a, m in item['key'][3]]
        fact['nil'] = fact.pop('valueType') == 'nil'
        fact['numeric'] = bool(fact['unit']['numerator'])
        fact['source'] = {'member': member, 'factId': fact['id']}
        facts.append(fact)
    return {'path': str(source), 'format': 'submission-candidate', 'facts': facts,
            'instanceMember': member, 'warnings': inspection.get('warnings', []),
            'officialGenerated': False, 'validationPassed': False, 'finalSubmission': False}
