"""Narrow, evidence-bound identities; recognition never certifies a filing.

An updated writer remains unverified until its signature, binary and behavior
have been reviewed. Registry display versions are not executable file versions.
"""
from copy import deepcopy


_EDITOR = {
    'id': 'fss-ifrs-editor-1.64.0.27',
    'name': '금융감독원 IFRS XBRL재무제표작성기',
    'executableName': 'IFRSEditor.exe',
    'productName': 'IFRS XBRL재무제표작성기',
    'fileVersion': '1.64.0.27',
    'sha256': '1d9e293d31a3f4f11db35ecc4f9622ee65a56273e735e1cabc7e3d454c489e57',
    'publisherOrganization': 'Financial Supervisory Service',
    'observedProgramVersion': '9.01',
    'observedProgramDate': '20261026',
    'observedInstallerVersion': '8.98',
    'identityEvidence': 'Locally installed official writer: PE metadata, SHA256 and valid Authenticode signature.',
    'identityStatus': 'verified-local-binary',
    'launchSupported': True,
    'automatedImportSupported': False,
    'finalSubmissionSupported': False,
    'sourceFormats': [{'extension': '.ixd', 'role': 'editor-source',
                       'status': 'official-sample-observed', 'automatedImportSupported': False}],
    'submissionFormats': [],
    'limitations': '편집 원본 IXD와 공식 검사 후 생성되는 제출 파일은 별도로 확인해야 합니다. 자동 입력·제출 생성은 검증하지 않았습니다.',
}


def profile_for_writer(metadata):
    """Return capabilities for one exact inspected identity, or explicit unknowns.

The certificate subject must contain an organization RDN, rather than merely
mentioning the organization inside an unrelated common name.
"""
    unknown = {'id': None, 'name': str(metadata.get('name', '')) if isinstance(metadata, dict) else '',
               'identityStatus': 'unverified', 'launchSupported': False,
               'automatedImportSupported': False, 'finalSubmissionSupported': False,
               'sourceFormats': [], 'submissionFormats': [],
               'limitations': '이 실행파일의 공식 작성기 버전·입출력 형식을 확인하지 않았습니다.'}
    if not isinstance(metadata, dict):return unknown
    subject = metadata.get('publisher', '')
    organizations = [part.strip()[2:].strip().strip('"').casefold() for part in str(subject).split(',')
                     if part.strip().casefold().startswith('o=')]
    if (metadata.get('sha256') == _EDITOR['sha256'] and metadata.get('signatureStatus') == 'Valid'
            and _EDITOR['publisherOrganization'].casefold() in organizations
            and metadata.get('name') == _EDITOR['productName']
            and metadata.get('version') == _EDITOR['fileVersion']):
        return deepcopy(_EDITOR)
    return unknown
