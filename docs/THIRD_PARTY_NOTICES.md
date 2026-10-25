# 함께 배포하는 구성요소

이 앱의 아이콘과 화면 구성은 프로젝트에서 직접 작성했습니다. 토스 로고·그래픽·폰트를 포함하지 않습니다. 토스 문서는 UX 원칙과 문구 작성의 참고 자료로 사용했습니다.

- **PySide6 / Qt 6.12.0 / Shiboken6:** Qt for Python 프로젝트가 제공하는 라이브러리입니다. 배포물 `licenses/`에 패키지의 라이선스 문서를 함께 제공합니다. Qt 공유 라이브러리는 `_internal`에 별도 파일로 배포하며 호환되는 라이브러리로 교체할 수 있는 폴더 형태를 유지합니다. 라이브러리를 수정하지 않았습니다. 프로젝트와 소스: https://code.qt.io/cgit/pyside/pyside-setup.git/ 및 https://code.qt.io/cgit/qt/qtbase.git/
- **Noto Sans KR:** Google Fonts 공식 저장소의 글꼴을 포함합니다. SIL Open Font License 1.1 문서는 `assets/fonts/OFL.txt`와 실행팩의 `licenses/NotoSansKR-OFL.txt`에 있습니다. https://github.com/google/fonts/tree/main/ofl/notosanskr
- **openpyxl 3.1.5:** Excel 읽기·쓰기 라이브러리입니다. 패키지에서 제공하는 라이선스 문서를 실행팩에 포함합니다. https://openpyxl.readthedocs.io/
- **et_xmlfile 2.0.0 / Pillow 12.3.0:** openpyxl의 XML 출력과 이미지 지원에 사용하는 라이브러리입니다. 패키지의 라이선스 문서를 실행팩에 포함합니다. https://foss.heptapod.net/openpyxl/et_xmlfile 및 https://python-pillow.github.io/
- **Python / PyInstaller:** Python 런타임과 PyInstaller 부트로더를 사용해 실행팩을 만듭니다. Python 라이선스를 실행팩에 포함하고, PyInstaller는 프로그램 배포에 대한 라이선스 예외를 제공합니다. https://www.python.org/ 및 https://pyinstaller.org/

구성요소의 구체적인 사용·수정·재배포 조건은 함께 제공한 원문 라이선스에 따릅니다.
