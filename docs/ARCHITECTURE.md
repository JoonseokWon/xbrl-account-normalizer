# v0.9 모듈 구조

화면은 Qt를 사용하지만 데이터 처리 계층은 Qt에 의존하지 않습니다. 데스크톱과 CLI는 같은 application 서비스를 호출합니다.

```text
main.py                         Windows GUI 진입점
convert.py                      CLI 어댑터와 기존 read_input/read_json 호환
desktop/
  theme/                        색상·간격·글자 크기·스타일
    typography.py               Windows 한글 글꼴 선택·힌팅·입력 안내 색상
  components/                   카드·버튼·배지·파일 영역·테이블·확인창
  models/                       Qt 테이블 데이터 모델
  screens/                      자료 준비 / 열 연결 / 계정 검토 / 결과 / 안내
  controllers/                  화면 이벤트와 백그라운드 작업 연결
    xbrl_export.py              XML 저장 진행률·취소 연결
    xbrl_inspection.py          저장 결과 폴더 선택과 재검사 실행
    jobs.py                     성공·오류·진행률·취소 신호 전달
  dialogs/xbrl_inspection.py     검사 결과·100행 미리보기·원본 이동·HTML 저장
  dialogs/filing.py              회사·공시 범위·비교기간·개념/역할 검색·항목 승인
  controllers/filing.py          원장 업무를 바꾸지 않고 별도 공시 준비 화면 열기
application/
  paths.py                      번들 리소스와 사용자 저장 위치 구분
  configuration.py              프로필·사전·열 연결 설정
  session.py                    하나의 작업 상태
  loading.py                    원본 읽기와 표준화 시작
  reviews.py                    계정 확인·거절·미확정 변경
  xbrl_export.py                원본 해시·매핑 확인, 원자적 XML 결과 저장
  xbrl_inspection.py            저장 결과의 XSD·해시·행 연결·금액 재검사
  xbrl_preview.py               저장한 행 연결의 한도 있는 페이지 읽기
  xbrl_source_refs.py           출처 해시 형식 확인과 원본 이동 조건
  exporting.py                  새 결과 폴더 저장과 이력 보관
  audit_export.py               확인 원장과 별도 보조자료로 통합감사 입력 생성
  filing.py                     공시 입력·공식 DTS/엑셀 참조·원본 검증·원자적 결과 저장
xbrl_filing/
  inputs.py                     빈 공시 엑셀 양식·CSV/JSON·서명 없는 .acfiling 업무
  model.py                      명시한 회사·기간·자료형·단위·승인과 중복 팩트 규칙
  writer.py                     공시 개념·시점/기간·명시적 차원의 XBRL 2.1 XML
  taxonomy.py                   로컬 실제 DTS·패키지 지문·Arelle 기술 검사
  runtime.py                    Arelle 검사를 별도 로컬 프로세스로 격리
  reconciliation.py             적용 가능한 재무상태표 대차등식 확인
  reporting.py                  공시 검사 HTML·DART 입력대사 CSV
  dart_excel.py                 DART 공식 엑셀의 개념·역할 메타데이터 읽기
  dart_handoff.py                엑셀 참조에 근거한 승인 대사표; XML 생성 없음
xbrl_gl/
  taxonomy.py                   공식 스키마 고정·오프라인 참조·택사노미 패키지
  writer.py                     GL journal/balance XML 순차 출력
  validation.py                 공식 XSD·원본 행·금액·코드·context 대사
  reporting.py                  한국어 HTML 검사 결과와 안전한 상대 파일 링크
  control.py                    협력적 취소 확인과 단계별 진행률 알림
vendor/xbrl-gl-2015/             수정하지 않은 공식 스키마·링크베이스 30개
core/
  values.py                     코드·일자·금액 규칙
  catalog.py                    사전·명시적 매핑 규칙
  mapping_engine.py             승인 이력과 후보 연결
  ledger.py                     원장 행과 전표 차대
  financial.py                  재무상태표 문맥
  aggregation.py                확인한 원장행의 표준 계정 집계
  bridge.py                     기존 감사 입력용 부분 데이터
  audit_contract.py             통합감사 7시트·보조파일·모듈 연결 규격
  audit_validation.py           회사·기간·시산표·별도 통제의 기계적 비교
io_xlsx/
  package_guard.py              XLSX 압축·XML 입력 한도
  inspection.py                 시트·열 이름 조회
  tables.py                     보조파일의 엄격한 확정값 표 읽기
  reader.py                     확정값 원본 읽기
  styling.py                    Excel 시트 스타일 생성
  writer.py                     검토 엑셀 시트 구성
normalizer.py                   작은 조정 계층과 이전 import 호환
suggestions.py                  이름 기반 후보와 설명
review_history.py               회사·시스템별 승인·거절 이벤트
workbook_export.py              이전 Excel export import 호환
```

UI는 원본 계정코드를 바꾸지 않으며 application 서비스를 통해서만 작업 상태를 변경합니다. 작업 중 화면 입력을 잠그고 백그라운드에서 파일을 처리합니다. 결과 엑셀과 JSON은 새 폴더에 저장합니다. EXE에 포함한 읽기 전용 리소스와 `%LOCALAPPDATA%/AccountDataNormalizer`의 로컬 이력·로그를 구분합니다.

XML 저장은 임시 폴더에서 출력·공식 XSD·원본 보존 대사·HTML/JSON 보고서를 만든 뒤 완료 폴더로 확정합니다. 취소는 행 처리·파일 해시 확인 중에 전달하며, 완료 확정 전에는 임시 출력만 정리하고 현재 업무와 이전 완료 결과를 유지합니다. 확정 이후 도착한 취소는 성공한 결과를 취소로 바꾸지 않습니다.

저장 결과 재검사는 현재 업무와 독립된 읽기 전용 서비스입니다. 저장된 JSON의 파일 경로를 그대로 신뢰하지 않고 결과 폴더 안의 XML·행 연결·스키마 패키지와 내장 공식 스키마를 확인합니다. 보고서와 파일을 함께 바꾼 경우의 원본 진위를 인증하거나 원본 원장을 다시 대사하는 서비스는 아닙니다. v0.9부터 공시 DTS 기술 검사용 Arelle 2.47.3을 실행팩에 포함합니다. 기존 GL 저장 결과 재검사와 공시 DTS 검사는 서로 다른 서비스입니다.

미리보기는 원장 전체를 테이블에 쌓지 않고 저장한 행 연결 메타데이터를 100행씩 읽습니다. 원본 해시와 행 위치·회사·계정이 현재 열린 업무와 일치하는 경우에만 원본 행으로 이동합니다. 출처 메타데이터의 형식이 잘못됐으면 원본 이동을 비활성화합니다. HTML 보고서는 외부 스크립트·네트워크 없이 열 수 있고, 재검사 HTML을 다른 폴더에 저장할 때는 상대 파일 링크를 생략합니다.

v0.5 추가 모듈:

- application/presets.py, catalogs.py, workfiles.py, json_store.py: 회사·ERP 설정, 버전 사전, 원본 포함 업무와 원자적 저장
- application/support_preparation.py: 회사별 보조자료 열 연결과 제공값 정규화
- core/journals.py, reconciliation.py, limits.py: 복합분개 그룹, 읽기 전용 대사와 공유 한도
- io_xlsx/delimited.py, records.py, streaming.py: CSV·TSV, 임의 보조표 확정값 읽기와 큰 검토 엑셀 저장
- desktop/dialogs/: 사전·보조자료·원본 행. components/journal_view.py: 전표와 차대변 상세
- desktop/controllers/work_actions.py: 업무 저장·복원·사전·입력 설정 동작

입력 설정은 기간·실제 보조파일 경로를 재사용하지 않습니다. 업무 파일은 원본 바이트를 포함하며 복원 시 해시를 확인하고 외부 승인 이력 없이 재계산합니다. 사전 변경은 승인 이력의 새 버전 범위를 만들며 현재 매핑을 미확정으로 바꿉니다. 보조자료 금액은 원장으로 생성하지 않습니다. 표준화 업무·저장 결과 재검사는 합계 25만 행을 지원합니다. 통합감사 v2.3 이상의 총계정원장 계약은 1,048,575행, 보조표는 시트당 1만 행으로 구분합니다.

공시 준비는 기존 Session을 수정하지 않는 별도 report 객체를 사용합니다. 기존 업무에서는 BS 표시값만 복사하며 거래 순증감으로 기말잔액·CF 등을 만들지 않습니다. 공시용 BS/PL/CF/CE/NOTE 팩트는 별도 확정 입력으로 제공하고, 같은 개념·회사·기간·차원·단위의 중복을 자동 합산하지 않습니다. 미승인 항목과 변경된 원본·택사노미는 결과 저장을 차단합니다.

`.acfiling`은 입력·승인·택사노미 지문을 담는 서명 없는 JSON입니다. 원본 바이트를 포함하는 `.acwork`와 달리 원본 파일·택사노미를 별도 보관합니다. 승인 이름과 파일 해시는 로그인 인증·전자서명·공식 원본 진위 인증을 대신하지 않습니다.

공시 XSD 경로는 실제 DTS의 자료형·기간·명시적 차원과 계산 1.0/1.1 관계를 검사합니다. 계산 연결에 필요한 팩트가 없으면 미수행 범위를 보고합니다. DART 공식 엑셀 경로는 개념 메타데이터와 승인 대사표만 다루고 `concept-metadata-only`, `xmlGenerated=false`를 기록합니다. 공식 IFRS/DART 택사노미 원본은 재배포하지 않으며 DART 최종 작성·제출·접수 검증도 별도입니다. 사용법과 확인 범위는 [IFRS_DART.md](IFRS_DART.md)를 참고하세요.
