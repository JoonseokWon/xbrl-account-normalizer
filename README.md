# 회계데이터 표준화

엑셀 원장과 재무상태표를 공통 계정코드로 연결하는 Windows 데스크톱 앱입니다. 원본 계정코드·행 출처를 남기면서 후보를 비교하고, 확인한 연결을 다음 작업에 다시 사용할 수 있습니다.

**v0.3.1-preview.1 — 사용자 검증 대기. 기능·회계 결과의 실행 검증은 수행하지 않았습니다. 화면 글꼴·배율 렌더링과 EXE 초기화·리소스 확인은 배포 준비 범위로 구분합니다.**

## Windows에서 시작하기

1. [GitHub 릴리스](https://github.com/JoonseokWon/xbrl-account-normalizer/releases/tag/v0.3.1-preview.1)의 Windows 실행팩 ZIP을 내려받아 압축을 모두 풀어요.
2. `AccountDataNormalizer.exe`를 실행해요. Python이나 Codex 설치는 필요하지 않아요.
3. EXE와 `_internal` 폴더를 함께 보관해요. 앱은 로컬 파일을 처리하며 런타임에 서버로 원장을 전송하지 않아요.

### 작업 순서

- **자료 준비:** 회사코드·원천시스템·확인자를 입력하고 엑셀 파일을 선택해요. 합성 예제로 화면을 살펴볼 수도 있어요.
- **열 연결:** 사용할 시트와 열 제목 행을 정하고, 원본 열을 계정코드·금액 등 표준 필드에 연결해요.
- **계정 검토:** 원본 코드, 후보, 추천 근거를 보고 표준 계정을 연결하거나 후보를 제외해요. 계정명·코드로 검색하고 미확정 계정만 볼 수 있어요.
- **변환 결과:** 미확정 행과 오류를 확인하고 검토 엑셀을 새 폴더에 저장해요. 결과 폴더를 앱에서 바로 열 수 있어요.

검토본은 미확정 계정이 있어도 저장할 수 있습니다. 실제 감사 연결 데이터는 오류·미확정 상태를 먼저 해결해야 합니다. 새 연결은 이름 유사도나 코드 일치만으로 자동 승인하지 않습니다.

## UI/UX와 모듈

[토스 UI/UX 가이드](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide)를 참고해 해요체, 명확한 행동 이름, 예상 가능한 이동, 정보 중심의 화면을 적용했습니다. 자료·작업 정보·연결 예시·요약을 서로 다른 크기의 카드에 배치한 벤토 그리드입니다. Windows에서는 왼쪽 내비게이션과 고정 상단 작업 버튼을 사용하고 본문은 창 크기에 따라 스크롤합니다. 토스 로고와 그래픽은 사용하지 않습니다.

계산·매핑, 엑셀 입출력, 작업 서비스, 화면, 공통 컴포넌트, 테마, 백그라운드 작업을 나눴습니다. [모듈 구조](docs/ARCHITECTURE.md)와 [UI 설계 반영 내용](docs/UI_DESIGN.md)을 확인할 수 있습니다. CLI도 같은 서비스를 사용합니다.

Windows에서는 설치된 맑은 고딕을 우선 사용하고, 해당 글꼴이 없으면 포함된 Noto Sans KR을 사용합니다. 본문 11pt·안내 10.5pt로 키우고 보조 글자와 입력 안내의 대비를 높였습니다. Windows 글꼴은 실행팩에 복사하지 않습니다.

## 연결 규칙

`00101 보통예금`, `00102 당좌예금` → `A1102 현금성 예금` → `CASH / 현금분석`처럼 다대일 계정 연결을 지원합니다. 현재 사전은 13개 항목의 실험용 자체 코드이며 공식 DART·IFRS XBRL 택사노미가 아닙니다.

- 한글·영문 별칭, 공백·구두점 정규화, 문자열 유사도로 상위 후보 3개와 근거를 제안합니다. 점수는 정확도·확률이 아닙니다.
- 승인 이력은 입력종류·회사·원천시스템·원본코드·계정명·사전 버전이 모두 같을 때 재사용합니다.
- 거절한 후보는 같은 범위에서 다시 추천하지 않습니다. 현재 사용자가 지정한 미확정 상태는 이력보다 우선합니다.
- 확인·거절 이력은 결과를 저장할 때 보관합니다. 확인자 이름은 텍스트 기록이며 로그인 인증은 아닙니다.

EXE의 로컬 이력과 오류 기록은 `%LOCALAPPDATA%/AccountDataNormalizer`에 저장합니다. 사용자 원본·이력·로그는 Git과 릴리스에 포함하지 않습니다.

## 입력과 결과의 범위

입력은 확정값 `.xlsx`, 20MB 이하, 시트당 50,000행·80열 이하입니다. 수식·매크로·외부 연결·내장 개체가 있으면 값으로 준비한 사본을 사용합니다. 원장 필수 정보는 회사·전기일·전표번호·행ID·계정코드·계정명·차변·대변입니다. 앞자리 0이 필요한 코드는 텍스트 셀로 보존합니다.

통화는 KRW이며 원/천원/백만원을 원으로 환산합니다. 개별 금액 절댓값 10조원 이하의 정수를 지원합니다. 양쪽 금액 공란, 음수 차대, 중복 전표행, 전표 차대 불일치는 이슈로 표시합니다. 한쪽 공란만 기본 프로필 규칙에 따라 0으로 처리합니다.

재무제표는 **BS 재무상태표**를 지원합니다. PL에는 기간 시작·종료 규격이 추가로 필요합니다. 상세·소계·합계를 구분하고 중복 합산하지 않습니다. 원장 당기순변동을 기말잔액으로 대체하지 않습니다.

결과 폴더에는 `계정표준화_검토.xlsx`, `standardized.json`, `audit_bridge.json`, 사용한 열 연결 설정인 `input-profile.json`이 있습니다. 원본은 덮어쓰지 않습니다. `audit_bridge.json`은 기존 감사 입력의 원장·계정매핑 두 표만 제공하며 기존 감사 앱에 직접 불러오는 기능과 공식 XBRL GL 출력은 아직 포함하지 않습니다. 시산표·독립 추출 통제·증빙·모듈별 자료는 추가로 필요합니다.

## 소스로 실행·빌드하기

Python 3.11 이상에서 `설치.cmd`를 실행한 다음 `변환실행.cmd`로 GUI를 엽니다. 또는:

```text
python -m pip install -r requirements.txt
python main.py
python convert.py "원본.xlsx" --company "COMPANY-A" --system "ERP-A"
python convert.py "원본.xlsx" --inspect
python convert.py "원본.xlsx" --column-map config/column_mapping.example.json
```

시트명·기본 별칭은 `config/profile.json`, 계정 사전은 `config/catalog.json`에서 설정합니다. CLI의 `--no-history`는 이력 읽기·저장을 모두 끄며 `--history`로 다른 이력을 지정할 수 있습니다.

Windows 실행팩 빌드:

```text
python -m pip install -r requirements-build.txt
python tools/build_windows.py
python tools/package_release.py
```

[수동 확인 목록](docs/MANUAL_VALIDATION.md)과 `tests/`는 사용자가 검증할 수 있도록 제공합니다. 이번 버전에서 기능 테스트를 실행하지 않았으며 이전 버전의 결과를 이번 버전의 통과 기록으로 사용하지 않습니다.

## 참고 자료

외부 프로젝트 코드를 복사하지 않고 구조를 참고했습니다: [account-standardizer](https://github.com/gimjunhyeon87-maker/account-standardizer)의 한글·영문 계정명 후보, [semantic-account-mapper](https://github.com/farhatparvin/semantic-account-mapper)의 승인·거절 피드백, [audit_standardizer](https://github.com/MartinMans/audit_standardizer)의 명시적 열 연결입니다. [global_ledger_translator](https://github.com/GenAICPA/global_ledger_translator)와 [Arelle](https://github.com/Arelle/Arelle)는 향후 XBRL GL 출력·검증 참고 자료입니다.

배포 라이브러리·글꼴의 라이선스는 [서드파티 안내](docs/THIRD_PARTY_NOTICES.md)와 실행팩 `licenses/`에서 확인할 수 있습니다.
