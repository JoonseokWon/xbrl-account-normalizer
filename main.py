"""Windows desktop entry point. Core services also work without Qt."""
import argparse
import json
from pathlib import Path
import os
import sys

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('input',nargs='?')
    parser.add_argument('--render-preview',help=argparse.SUPPRESS)
    parser.add_argument('--diagnostics',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.render_preview:os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtCore import QTimer
    from application.paths import resources
    from application.configuration import default_profile
    from desktop.theme.styles import stylesheet
    from desktop.window import MainWindow
    from desktop.controllers.app import AppController
    from version import VERSION
    app=QApplication(sys.argv[:1]);app.setApplicationName('회계데이터 표준화');app.setOrganizationName('AccountDataNormalizer')
    QFontDatabase.addApplicationFont(str(resources()/'assets/fonts/NotoSansKR.ttf'))
    app.setStyle('Fusion');app.setFont(QFont('Noto Sans KR',10));app.setStyleSheet(stylesheet())
    window=MainWindow(default_profile());controller=AppController(window);window.controller=controller
    if args.diagnostics:
        paths=['config/profile.json','config/catalog.json','assets/app-icon.svg','samples/계정매핑_합성입력.xlsx']
        data={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),
              'resources':{path:(resources()/path).is_file() for path in paths},'scope':'startup and resource discovery only; no conversion run'}
        Path(args.diagnostics).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0 if all(data['resources'].values()) else 1
    window.show()
    if args.render_preview:
        app.processEvents()
        target=Path(args.render_preview);target.parent.mkdir(parents=True,exist_ok=True)
        if not window.grab().save(str(target)):raise RuntimeError('화면 미리보기를 저장하지 못했습니다.')
        return 0
    if args.input:QTimer.singleShot(0,lambda:controller.open_file(args.input))
    return app.exec()

if __name__=='__main__':
    raise SystemExit(main())
