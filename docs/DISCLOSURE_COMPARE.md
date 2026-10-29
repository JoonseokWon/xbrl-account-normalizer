# DSD·IXD 숫자와 텍스트 대사

이 기능은 로컬 공시 원문 표와 제출용 IXD 인스턴스의 **사용자가 확인한 대응**을 비교합니다. 다른 서비스의 소스, 프로그램, 비공개 화면 또는 산출물을 분석하지 않고 독립적으로 구현했습니다.

## 화면에서 사용하기

v0.14의 병합 머리글·대응 후보 3개·한글 택사노미 이름·부호/단위/단수 차이 필터는 [개선 기능 사용법](DISCLOSURE_ASSISTANCE.md)을 참고하세요. 후보 선택과 대응 확인은 별도 단계입니다.

1. **공시 검토 → DSD·IXD 숫자 대사**를 엽니다.
2. XML 표를 포함한 DSD/ZIP 또는 공시 원문 XML과 제출용 IXD를 선택합니다.
3. DSD 표의 셀과 IXD 팩트를 각각 고릅니다. 회사 식별자, 개념, 시점/기간, 통화·단위, 연결/별도를 포함한 차원, 언어와 DSD의 열 제목을 확인합니다.
4. DSD 표의 표시 단위에 따라 금액 배율을 선택하고 **대응 확인**을 누릅니다. 예를 들어 천원 표시값 `1,234`를 원 단위 팩트와 비교할 때 배율은 `1000`입니다. 계정명만으로 자동 승인하지 않습니다.
5. 대사를 실행하고 일치, 금액 차이, 측정조건 차이, nil 차이, 미대응, 중복, 미지원 항목을 확인합니다. 대응표와 결과를 JSON으로 저장해 같은 원본에서 재사용할 수 있습니다.

XML TABLE/TR/TD·TH(및 TE/TU) 표를 읽습니다. 행·열 병합은 실제 앵커 위치를 보존합니다. 단일 XML, XML이 들어 있는 ZIP 기반 DSD, OpenDART 공시 원문 ZIP이 입력 대상입니다. 모든 DART 편집기의 독자적 바이너리 형식이나 완전한 DSD 스키마를 구현했다는 의미는 아닙니다. 읽을 수 있는 XML 표가 없는 파일은 지원하지 않는 형식으로 표시하며, DART에서 XML 원문 사본을 준비해야 합니다.

## 비교와 승인 범위

- IXD는 기존 검사기로 제출용 패키지 후보 구조·파일 참조·ZIP 무결성을 확인한 뒤, METAINFO에 선언된 인스턴스만 읽습니다. 편집용 IXD는 제출용 팩트 대사 입력으로 사용하지 않습니다.
- DSD 제목·기간·단위 문구는 확인을 돕는 힌트입니다. 회사·기간·연결/별도·차원을 계정명이나 숫자만으로 추론해 승인하지 않습니다. 사용자가 고른 IXD의 전체 측정조건을 대응표에 명시적으로 보관합니다.
- 연결/별도는 서로 다른 차원 멤버일 때 서로 다른 측정조건입니다. 차원 축, 멤버, segment/scenario 배치를 모두 비교합니다. 형식 미지원 차원과 영구 기간 팩트는 미지원/확인 필요로 남깁니다.
- 숫자는 Decimal로 정확히 비교하고 차이는 **DSD 환산값 − IXD 값**입니다. 천원·백만원 변환 배율은 사용자가 지정합니다. 숫자 문자열 `1,234`, 괄호 음수 `(20)`, 유니코드 마이너스를 읽으며 `%`는 비율로 환산합니다. 통화 환산·반올림 허용오차·합산은 추정하지 않습니다.
- 공란, `-`, nil, 0은 서로 다릅니다. 공란·대시를 0으로 채우지 않습니다. nil 대응은 별도의 명시적 결정이 필요하며 기본 화면에서는 차이로 표시됩니다.
- 같은 측정조건의 중복 IXD 팩트는 값이 같더라도 모호한 대상으로 표시합니다. 서로 다른 DSD 셀이 같은 팩트를 반복 표시하는 경우에는 각각 독립적으로 비교할 수 있으며 값을 합산하지 않습니다.
- 확인되지 않은 대응, 미대응 숫자 셀, 중복, 미지원 항목이 남아 있으면 전체 결과를 일치로 표시하지 않습니다. TH/THEAD의 제목 숫자는 미대응 금액 범위에서 제외합니다. 비교하지 않은 IXD 팩트 개수는 별도로 표시합니다.
- 대응표에는 DSD·IXD SHA-256이 함께 저장됩니다. 어느 원본이든 변경되면 기존 대응표의 실행을 차단하고 다시 확인하도록 안내합니다. 셀 ID는 원본 파일 안 XML 멤버·표·행·열 위치입니다. 원본을 덮어쓰거나 압축을 디스크로 풀지 않습니다.
- 대사 `pass`는 확인한 대응 범위에서의 값·측정조건 일치입니다. 전체 공시·주석 완전성, 회계 판단, 택소노미·계산 링크 검증, 공식 생성, 기술검사 통과 또는 실제 DART 접수를 의미하지 않습니다.

## 코드 API

```python
from xbrl_filing.disclosure_compare import (
    inspect_disclosures, build_mapping, compare_disclosures,
)

inventory = inspect_disclosures('보고서.dsd', '제출후보.ixd')
# 화면에서 원본 셀과 팩트 측정조건을 확인한 뒤 호출합니다.
pair = build_mapping(inventory, 'contents.xml#t1:r2:c2', 'cash-current', scale='1000')
mapping = {
    'schema': 'account-normalizer-disclosure-mapping/1',
    'sourceHashes': inventory['sourceHashes'],
    'mappings': [pair],
}
report = compare_disclosures('보고서.dsd', '제출후보.ixd', mapping)
```

`inspect_disclosures`는 `dsd.cells/tables`, `ixd.facts`, `sourceHashes`, `sourceUnchanged`, `errors/warnings`를 반환합니다. 오류 시 팩트/셀 목록을 비웁니다. `compare_disclosures`의 결과는 `status`, `rows`, `counts`, `errors/warnings`로 구성한 JSON 직렬화 가능 객체입니다. 저장된 대응표는 익명 목록이 아닌 스키마·원본 해시가 있는 객체여야 합니다.

파일당 DSD 100MB, 단일 XML 32MB, XML 64개, ZIP 항목 2,000개·해제 합계 250MB, 표 2,000개, 셀 100,000개 이내입니다. 기존 IXD 검사기의 별도 한도를 적용합니다. DTD/외부 엔티티, 경로 이탈, ZIP 중복 경로·심볼릭 링크·실행 파일·암호화·손상된 압축을 차단합니다. XML/스타일/매크로를 실행하지 않으며 네트워크 요청을 하지 않습니다.

## 합성 예제와 검사

`xbrl_filing.disclosure_compare.examples.create_comparison_example(새폴더)`는 당기·전기 금액과 괄호 음수의 세 대응을 가진 합성 DSD, 최소 인식 구조 IXD, 대응표를 만듭니다. 해당 IXD는 공식 작성기 생성·택소노미 검증·제출용 파일이 아니며 실제 공시에 사용하면 안 됩니다. 공식 작성기 및 택소노미 파일은 예제에 포함하지 않습니다.

테스트는 스케일 비교, 전기 구분, 금액 변경, 회사·개념·기간·통화·차원·언어 차이, nil·공란 구분, 원본 변경 대응 차단, 중복 측정조건, 병합 셀과 ZIP/XML 안전을 확인합니다.

## 참고한 공개 공식 자료

- [금융감독원 OpenDART 공시서류 원본파일 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003): 원문 제공이 ZIP 바이너리이며 브라우저에서 `.xml`로 내려받은 경우 ZIP으로 확인할 수 있음을 안내합니다. 이 앱은 API 인증키를 요구하지 않고 사용자가 보유한 로컬 원문을 읽습니다.
- [금융감독원 OpenDART 원문 활용 소개](https://opendart.fss.or.kr/intro/main.do): 공시보고서 XML 원문 활용을 안내합니다.
- [금융감독원 재무제표 원본파일(XBRL) API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2019019): XBRL 원본 ZIP과 보고서 코드·접수번호 구분을 참고했습니다. XBRL 원본 ZIP과 IXD 제출용 패키지를 동일한 형식으로 취급하지 않습니다.
- [XBRL 2.1 공식 규격](https://specifications.xbrl.org/work-product-index-group-base-spec-base-spec.html): context, entity, period, unit, nil과 중복 팩트의 별도 측정조건을 참고했습니다.
- [금융감독원 DART 기업공시 길라잡이](https://dart.fss.or.kr/info/main.do?menu=510): 편집용 DSD 문서, 파일 형식검사, 전송파일 생성·접수가 구분됨을 참고했습니다.
