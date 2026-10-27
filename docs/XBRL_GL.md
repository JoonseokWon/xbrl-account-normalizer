# XBRL GL XML 저장

v0.7.0-preview.1은 XBRL International의 **XBRL GL 2015 COR+BUS** 택사노미에 맞는 **XBRL 2.1 XML 인스턴스**를 저장합니다. 원장·전표와 BS 표시값을 교환하기 위한 규격입니다. 재무제표 공시용 IFRS·DART 택사노미와 DART 제출 형식은 지원 범위가 아닙니다.

## 사용하는 방법

1. 새 파일을 열고 계정 연결을 확인하거나 기존 `.acwork` 업무를 엽니다.
2. 오류와 미확정 계정을 모두 해결합니다.
3. **변환 결과 → XBRL GL XML 저장**을 누르고 결과를 보관할 폴더를 선택합니다.
4. 공식 스키마 검사와 원본 보존 검사를 통과하면 새 결과 폴더를 표시합니다. 실패한 파일을 완료본으로 남기지 않습니다.

원장에는 회사별 `journal-001.xbrl` 형식의 파일을 만듭니다. BS는 회사·기준일별 `balance-001.xbrl`로 구분합니다. 계정·시스템·전표·행번호 앞자리 0을 보존하며, 큰 원장도 행을 생략하거나 분할하지 않습니다. 원본 행이 불연속이어도 같은 전표를 묶고 XML의 detail ID를 통해 원래 행으로 돌아갈 수 있습니다.

## 함께 저장하는 파일

| 파일 | 내용 |
|---|---|
| `*.xbrl` | 공식 GL 태그·namespace를 사용하는 XML 인스턴스 |
| `xbrl-gl-2015-taxonomy.zip` | 공식 스키마·링크베이스 원본과 오프라인 참조용 카탈로그 |
| `validation-report.json` | 스키마·행수·금액·코드·통화·회사·기간 검사와 파일 SHA256 |
| `row-map.jsonl` | XML detail ID별 원본 파일·시트·행과 매핑, 행별 작성자 |
| `읽어주세요.txt` | 다른 도구에서 여는 순서와 검사 범위 |

스키마·링크베이스 30개는 원본을 수정하지 않고 포함하며, `vendor/xbrl-gl-2015/manifest.json`에 공식 출처와 SHA256을 기록합니다. 자체 구성한 오프라인 패키지이며 XBRL International 인증을 받은 프로그램이라는 의미는 아닙니다. 원장과 파일은 앱 실행 중 외부 서버로 전송하지 않습니다.

## 값의 의미

| 원본 또는 매핑 | GL XML 필드 |
|---|---|
| 회사코드 | `xbrli:entity/xbrli:identifier`, 로컬 회사코드 식별 scheme |
| 전표번호·원본 행ID | `gl-cor:entryNumber`, `gl-cor:lineNumber` |
| 원본 계정코드·계정명 | `gl-cor:accountMainID`, `gl-cor:accountMainDescription` |
| 연결한 공통 코드·이름 | `gl-cor:accountSub`, type `app-standard-account` |
| 감사 리드 | `gl-cor:accountSub`, type `app-audit-lead` |
| 차변·대변 | 양수 `gl-cor:amount`와 `gl-cor:debitCreditCode` D/C |
| 전기일 | `gl-cor:postingDate` |
| 은행·계좌·부서·프로젝트 | 원본 종류를 구분한 `gl-cor:accountSub` |
| 거래처·증빙번호 | `gl-cor:identifierReference`, `gl-cor:documentNumber` |

`A1102` 같은 기존 공통 코드는 자체 계정체계의 값으로 남습니다. 이를 IFRS/DART 공식 재무제표 개념이라고 표시하지 않습니다. 실제 GL 태그와 자체 코드 값을 구분합니다. LEI·사업자등록번호가 없는 입력에 공식 등록 식별자를 임의로 만들어 붙이지 않고, 회사코드임을 나타내는 로컬 scheme을 사용합니다.

모든 GL fact의 context는 택사노미가 요구하는 instant 유형이며, 원장 기간은 `periodCoveredStart/End`, 개별 전기일은 `postingDate`로 기록합니다. 기간 입력이 없으면 원장 전기일 최소·최대에서 출력 범위를 정합니다. KRW 원 단위 정수이므로 금액은 ISO 4217 KRW와 `decimals="0"`로 표시합니다. 차대가 모두 0인 행은 금액 0·D로 기록하며 원본의 두 금액은 행 연결 파일에 보존합니다.

BS의 `amount`는 원본의 기말 표시값·부호를 유지합니다. 부채의 양수 표시값을 임의로 차변 잔액으로 해석하지 않으며 D/C 코드를 만들지 않습니다. 상세·소계·합계를 각 원본 행으로 보존하고 중복 합산하지 않습니다. 이 파일은 `entriesType=balance`인 GL 자료이며 IFRS/DART 재무제표 공시 인스턴스가 아닙니다.

## 검사의 범위

앱은 포함한 공식 XSD를 오프라인으로 검사하고, XML을 다시 읽어 원본과 행·금액·차대·전표·코드·세부정보·통화·context를 대사합니다. 원본 파일 해시가 불러온 뒤 변경됐으면 저장을 중단합니다. DTD와 외부 임의 스키마 참조를 차단합니다.

릴리스 검사에서는 별도 Arelle로 10개 회사와 BS XML의 XBRL 2.1 적합성을 확인합니다. 앱의 매번 저장 검사는 공식 XSD와 생성 프로필 대사이며, Arelle 엔진은 Windows 실행팩에 포함하지 않습니다. 검사 통과는 계정 분류의 회계 적정성·감사 결론·공시 접수 수리를 보장하지 않습니다.

다른 XBRL 도구에서 오프라인으로 열 때는 함께 저장한 택사노미 ZIP을 패키지로 등록합니다. Arelle 예:

```text
arelleCmdLine --file journal-001.xbrl --packages xbrl-gl-2015-taxonomy.zip --workOffline --validate
```

CLI에서는 `python convert.py "확인한업무.acwork" --xbrl --out "결과폴더"`를 사용할 수 있습니다. 기존 검토 엑셀·통합감사 입력 저장도 계속 지원합니다.

## 공식 참고 문서

- [XBRL GL 2015 Recommendation 목록](https://specifications.xbrl.org/work-product-index-xbrl-gl-xbrl-gl-2015.html)
- [GL Framework 2015](https://www.xbrl.org/int/gl/2015-03-25/gl-framework-REC-2015-03-25.html)
- [GL 기술 아키텍처](https://www.xbrl.org/int/gl/2015-03-25/GLTFTA-REC-2015-03-25.html)
- [실제로 참조하는 COR+BUS 진입점](https://www.xbrl.org/taxonomy/int/gl/2015-03-25/plt/case-c-b/gl-plt-all-2015-03-25.xsd)
- [Arelle CLI 검증 방법](https://arelle.readthedocs.io/en/latest/command_line.html)
