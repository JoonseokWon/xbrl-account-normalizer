# 모듈 구조

화면은 Qt를 사용하지만 데이터 처리 계층은 Qt에 의존하지 않습니다. 데스크톱과 CLI는 같은 application 서비스를 호출합니다.

```text
main.py                         Windows GUI 진입점
convert.py                      CLI 어댑터와 기존 read_input/read_json 호환
desktop/
  theme/                        색상·간격·스타일
  components/                   카드·버튼·배지·파일 영역·테이블·확인창
  models/                       Qt 테이블 데이터 모델
  screens/                      자료 준비 / 열 연결 / 계정 검토 / 결과 / 안내
  controllers/                  화면 이벤트와 백그라운드 작업 연결
application/
  paths.py                      번들 리소스와 사용자 저장 위치 구분
  configuration.py              프로필·사전·열 연결 설정
  session.py                    하나의 작업 상태
  loading.py                    원본 읽기와 표준화 시작
  reviews.py                    계정 확인·거절·미확정 변경
  exporting.py                  새 결과 폴더 저장과 이력 보관
core/
  values.py                     코드·일자·금액 규칙
  catalog.py                    사전·명시적 매핑 규칙
  mapping_engine.py             승인 이력과 후보 연결
  ledger.py                     원장 행과 전표 차대
  financial.py                  재무상태표 문맥
  aggregation.py                확인한 원장행의 표준 계정 집계
  bridge.py                     기존 감사 입력용 부분 데이터
io_xlsx/
  package_guard.py              XLSX 압축·XML 입력 한도
  inspection.py                 시트·열 이름 조회
  reader.py                     확정값 원본 읽기
  styling.py                    Excel 시트 스타일 생성
  writer.py                     검토 엑셀 시트 구성
normalizer.py                   작은 조정 계층과 이전 import 호환
suggestions.py                  이름 기반 후보와 설명
review_history.py               회사·시스템별 승인·거절 이벤트
workbook_export.py              이전 Excel export import 호환
```

UI는 원본 계정코드를 바꾸지 않으며 application 서비스를 통해서만 작업 상태를 변경합니다. 작업 중 화면 입력을 잠그고 백그라운드에서 파일을 처리합니다. 결과 엑셀과 JSON은 새 폴더에 저장합니다. EXE에 포함한 읽기 전용 리소스와 `%LOCALAPPDATA%/AccountDataNormalizer`의 로컬 이력·로그를 구분합니다.
