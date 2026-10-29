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
    parser.add_argument('--self-test-xbrl',help=argparse.SUPPRESS)
    parser.add_argument('--xbrl-check-rows',type=int,default=0,help=argparse.SUPPRESS)
    parser.add_argument('--filing-worker',nargs=2,help=argparse.SUPPRESS)
    parser.add_argument('--self-test-filing',help=argparse.SUPPRESS)
    parser.add_argument('--filing-taxonomy',help=argparse.SUPPRESS)
    parser.add_argument('--filing-dart-reference',help=argparse.SUPPRESS)
    parser.add_argument('--self-test-official-writer',nargs=2,help=argparse.SUPPRESS)
    parser.add_argument('--official-editor-document',help=argparse.SUPPRESS)
    parser.add_argument('--self-test-disclosure',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.self_test_disclosure:
        from tools.verify_disclosure import run_checks
        result=run_checks(args.self_test_disclosure)
        return 0 if result['ok'] else 1
    if args.self_test_official_writer:
        from tools.verify_official_writer import run_checks
        result=run_checks(*args.self_test_official_writer,editor_document=args.official_editor_document)
        return 0 if result['ok'] else 1
    if args.filing_worker:
        from xbrl_filing.runtime import worker_main
        return worker_main(*args.filing_worker)
    if args.self_test_filing:
        from tools.verify_filing import run_checks
        run_checks(args.self_test_filing,args.filing_taxonomy,args.filing_dart_reference)
        return 0
    if args.self_test_xbrl:
        from tools.verify_xbrl import run_checks
        run_checks(args.self_test_xbrl,args.xbrl_check_rows)
        return 0
    if args.render_preview and sys.platform!='win32':os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontInfo
    from PySide6.QtCore import QTimer,Qt
    from application.paths import resources
    from application.configuration import default_profile,default_catalog
    from desktop.theme.styles import stylesheet
    from desktop.theme.typography import configure_typography
    from desktop.window import MainWindow
    from desktop.controllers.app import AppController
    from version import VERSION
    app=QApplication(sys.argv[:1]);app.setApplicationName('회계데이터 표준화');app.setOrganizationName('AccountDataNormalizer')
    app.setStyle('Fusion');font_family=configure_typography(app);app.setStyleSheet(stylesheet(font_family))
    window=MainWindow(default_profile());controller=AppController(window);window.controller=controller
    if args.diagnostics:
        from desktop.dialogs.filing import FilingDialog
        from importlib.metadata import version as package_version
        filing_dialog=FilingDialog(None,window)
        filing_editor_limit=filing_dialog.fact_value.maxLength();filing_dialog.deleteLater()
        from suggestions import suggest_accounts
        catalog=default_catalog()
        checks={name:suggest_accounts(name,'원장',catalog['accounts'])[0]['code']==target for name,target in
                [('관리부 / 전산소프트웨어자산','A1501'),('원천세예수금 (본점)','L2205'),('온라인광고비 - 국내사업','E5210')]}
        paths=['config/profile.json','config/catalog.json','assets/app-icon.svg','samples/계정매핑_합성입력.xlsx','vendor/xbrl-gl-2015/manifest.json']
        from xbrl_gl.taxonomy import verify_taxonomy
        taxonomy=verify_taxonomy()
        data={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),
              'resources':{path:(resources()/path).is_file() for path in paths},
              'display':{'platform':app.platformName(),'devicePixelRatio':window.devicePixelRatioF(),
                         'fontFamily':QFontInfo(app.font()).family(),'pointSize':app.font().pointSizeF()},
                'catalogVersion':catalog['version'],'catalogEntries':len(catalog['accounts']),'candidateSmokeChecks':checks,
                'xbrlTaxonomyFiles':len(taxonomy['files']),'xbrlEntryPoint':taxonomy['entryPoint'],
                'filingValidator':package_version('arelle-release'),'filingNoteEditorLimit':filing_editor_limit,
                'scope':'startup, resource discovery and three dictionary candidates only; no conversion run'}
        Path(args.diagnostics).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0 if all(data['resources'].values()) and all(checks.values()) else 1
    if args.render_preview:window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
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
