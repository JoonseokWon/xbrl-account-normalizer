# 함께 배포하는 구성요소

이 앱의 아이콘과 화면 구성은 프로젝트에서 직접 작성했습니다. 토스 로고·그래픽·폰트를 포함하지 않습니다. 토스 문서는 UX 원칙과 문구 작성의 참고 자료로 사용했습니다.

- **PySide6 / Qt 6.12.0 / Shiboken6:** Qt for Python 프로젝트가 제공하는 라이브러리입니다. 배포물 `licenses/`에 패키지의 라이선스 문서를 함께 제공합니다. Qt 공유 라이브러리는 `_internal`에 별도 파일로 배포하며 호환되는 라이브러리로 교체할 수 있는 폴더 형태를 유지합니다. 라이브러리를 수정하지 않았습니다. 프로젝트와 소스: https://code.qt.io/cgit/pyside/pyside-setup.git/ 및 https://code.qt.io/cgit/qt/qtbase.git/
- **Noto Sans KR:** Windows 한글 글꼴을 사용할 수 없는 환경에 대비해 Google Fonts 공식 저장소의 글꼴을 포함합니다. SIL Open Font License 1.1 문서는 `assets/fonts/OFL.txt`와 실행팩의 `licenses/NotoSansKR-OFL.txt`에 있습니다. 맑은 고딕은 사용자의 Windows에 설치된 글꼴을 참조하며 파일을 배포하지 않습니다. https://github.com/google/fonts/tree/main/ofl/notosanskr
- **openpyxl 3.1.5:** Excel 읽기·쓰기 라이브러리입니다. 패키지에서 제공하는 라이선스 문서를 실행팩에 포함합니다. https://openpyxl.readthedocs.io/
- **et_xmlfile 2.0.0 / Pillow 12.3.0:** openpyxl의 XML 출력과 이미지 지원에 사용하는 라이브러리입니다. 패키지의 라이선스 문서를 실행팩에 포함합니다. https://foss.heptapod.net/openpyxl/et_xmlfile 및 https://python-pillow.github.io/
- **Python / PyInstaller:** Python 런타임과 PyInstaller 부트로더를 사용해 실행팩을 만듭니다. Python 라이선스를 실행팩에 포함하고, PyInstaller는 프로그램 배포에 대한 라이선스 예외를 제공합니다. https://www.python.org/ 및 https://pyinstaller.org/

구성요소의 구체적인 사용·수정·재배포 조건은 함께 제공한 원문 라이선스에 따릅니다.

- **lxml 6.1.3:** XML 출력·공식 XSD 검증에 사용합니다. 배포 라이선스와 libxml2/libxslt 관련 고지를 실행팩 `licenses/lxml/`에 포함합니다. https://lxml.de/ 및 https://github.com/lxml/lxml
- **XBRL International GL 2015 COR+BUS:** 공식 스키마와 링크베이스 원본 30개를 수정 없이 `vendor/xbrl-gl-2015/`에 포함합니다. 원본 저작권 고지와 legal 링크를 유지하며 출처·SHA256은 manifest에 기록합니다. 오프라인 패키지의 구성만 프로젝트에서 추가했습니다. https://specifications.xbrl.org/work-product-index-xbrl-gl-xbrl-gl-2015.html 및 https://www.xbrl.org/legal/
- **Arelle 2.47.3:** 릴리스 검증용으로 별도 사용했습니다. Windows 앱에는 포함하지 않습니다. https://github.com/Arelle/Arelle
