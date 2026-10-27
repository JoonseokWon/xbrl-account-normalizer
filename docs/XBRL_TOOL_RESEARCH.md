# 외부 도구 조사와 v0.8 개선

현재 목적은 회사별 계정명·원장을 공통 코드와 XBRL GL로 연결하는 것입니다. 아래는 공식 문서에서 확인한 기능과 이 앱에 적용한 판단을 구분한 기록입니다. 외부 프로그램 코드는 복사하지 않았습니다.

| 공식 자료에서 확인한 방식 | 이 앱에 적용한 개선 |
|---|---|
| Arelle는 저장한 인스턴스를 불러와 검증하고 로그를 남김 | 원본 원장을 다시 열지 않고 저장 결과의 XML·해시·공식 스키마·행 연결을 재검사 |
| Altova MapForce는 출력 미리보기, 출력 검증, 오류·경고 메시지 창을 제공 | 별도의 한국어 검사 결과 화면, 오류가 발생한 파일·원본 위치 표시 |
| MapForce는 메시지에서 해당 출력 요소로 이동하며 큰 출력은 표시량을 제한 | 100행씩 출력 행·원본 연결을 보고, 현재 업무와 원본 해시가 일치할 때 원본 행으로 이동 |
| Workiva는 XBRL 생성마다 브라우저에서 읽고 보관하는 HTML 계산 보고서를 제공 | 자체 GL 검사 항목·회사·기간·행수·차대 합계를 담은 오프라인 HTML 보고서 |

Workiva의 계산 규칙은 재무제표 공시용입니다. 여기서는 보고서를 읽고 확인하는 방식만 참고했고, SEC/ESEF 계산 규칙을 원장 GL 자료에 적용하지 않았습니다. XBRL International의 단계별 검증 설명을 참고해 스키마·값 보존·업무 규칙의 범위를 나눠 표시합니다.

진행률과 취소는 위 경쟁 제품에서 확인했다는 주장이 아닌, 이 앱의 25만 행 처리 경험에서 추가한 개선입니다. XML 저장/내용 확인 단계와 처리 행 수를 표시하고, 취소는 기존 업무·이전 결과를 보존하며 미완성 임시 출력만 정리합니다.

## 공식 출처

- [Arelle CLI의 파일·패키지·검증·로그 옵션](https://arelle.readthedocs.io/en/latest/command_line.html)
- [Altova MapForce 출력 검증과 미리보기](https://www.altova.com/manual/Mapforce/mapforcebasic/mf_mapfund_generalfeat_validate.html)
- [Workiva HTML 계산 보고서](https://support.workiva.com/hc/en-us/articles/360035641492-The-calculation-report)
- [XBRL International의 검증 단계 설명](https://www.xbrl.org/the-standard/what/key-concepts-in-xbrl/validation/)

## 이후 우선순위

현재는 단일 통화 KRW와 자체 공통 계정체계를 사용합니다. 다음 확장은 실제 회사 자료에 근거한 계정 정의·매핑 사례 확대, 전기 매핑 변경 비교, 회사가 정한 IFRS/DART 개념 연결·확인 과정, 다중 통화 원장입니다. 공식 재무제표 개념을 연결하려면 사용 택사노미 버전과 연결/별도·표시 방법 등 회사별 기준을 먼저 정해야 합니다.
