from pathlib import Path
from PySide6.QtCore import QObject,QUrl,QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog
from application.configuration import default_profile,default_catalog,configure_profile
from application.loading import load_batch
from application.reviews import apply_review
from application.exporting import export_session
from application.paths import user_data,default_outputs
from io_xlsx.inspection import inspect_workbook
from .jobs import Jobs
from desktop.components.confirmation import confirm
from .audit_export import choose_and_export
from .xbrl_export import choose_and_export_xbrl
from .xbrl_inspection import choose_and_inspect
from .filing import open_filing
from .work_actions import WorkActions
from application.catalogs import load_catalog
from application.support_preparation import prepare_support
from desktop.dialogs.support import SupportDialog

class AppController(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.jobs=Jobs();self.path=None;self.pending_path=None;self.session=None;self.profile=default_profile();self.catalog=default_catalog();self.close_after_work=False;self.force_close=False;self.export_cancel=None
        window.close_guard=self.can_close
        self.home,self.columns,self.mapping,self.results,self.help=window.pages
        self.paths=[];self.pending_paths=[];self.pending_preset=None;self.support_preset={}
        try:self.catalog=load_catalog()
        except Exception as exc:window.notice.set_message('저장한 사전을 읽지 못해 기본 사전을 열었어요: '+str(exc),True)
        self.home.chooseRequested.connect(self.choose_file);self.home.fileDropped.connect(self.open_file)
        window.fileRequested.connect(self.choose_file)
        window.cancelRequested.connect(self.cancel_xbrl_export)
        self.columns.inspectRequested.connect(self.inspect)
        self.columns.loadRequested.connect(self.load);self.mapping.resultsRequested.connect(lambda:window.show_page(3))
        self.mapping.editor.decisionRequested.connect(self.review)
        self.results.exportRequested.connect(self.export);self.results.openFolderRequested.connect(self.open_results)
        self.results.auditExportRequested.connect(lambda:choose_and_export(self))
        self.results.xbrlExportRequested.connect(lambda:choose_and_export_xbrl(self))
        self.results.xbrlInspectRequested.connect(lambda:choose_and_inspect(self))
        self.results.filingRequested.connect(lambda:open_filing(self))
        self.results.openReportRequested.connect(self.open_report)
        self.results.supportRequested.connect(self.connect_support)
        self.help.openDataRequested.connect(self.open_data);window.actionRequested.connect(self.action)
        self.work_actions=WorkActions(self)
    def action(self,index):
        if self.window.busy:return
        if index==0:
            if self.window.has_file:self.window.show_page(1)
            else:self.choose_file()
        elif index==1:self.load()
        elif index==2:self.window.show_page(3)
        elif index==3:
            if self.results.xbrl_save.isEnabled():choose_and_export_xbrl(self)
            else:self.export()
    def choose_file(self):
        if self.window.busy:return
        folder=self.path.parent if self.path else Path.home()/'Documents'
        paths,_=QFileDialog.getOpenFileNames(self.window,'같은 회사·양식의 자료 파일을 선택해 주세요',str(folder),'원장·재무상태표 (*.xlsx *.csv *.tsv)')
        if paths:self.open_files(paths)
    def open_file(self,path):
        self.open_files([path])
    def open_files(self,paths):
        if self.window.busy:return
        if self.session and self.session.dirty:
            if not confirm(self.window,'새 파일로 작업을 시작할까요?','저장하지 않은 계정 연결이 있어요. 새 파일을 열면 현재 작업과 회사 정보를 바꿔요.','새 파일 열기'):return
        self.pending_paths=[Path(p) for p in paths];self.pending_path=self.pending_paths[0]
        self.window.set_busy(True,'엑셀의 시트와 열 이름을 읽고 있어요.')
        self.jobs.start(lambda:inspect_workbook(self.pending_path,1),self.file_ready,self.failure)
    def file_ready(self,sheets):
        previous=self.path;self.path=self.pending_path;self.pending_path=None;self.session=None
        self.paths=self.pending_paths;self.pending_paths=[];self.profile=default_profile();self.pending_preset=None;self.support_preset={}
        self.window.has_file=True;self.window.has_session=False
        self.home.begin_file(self.path,reset_details=previous is not None)
        if len(self.paths)>1:self.home.drop.title.setText(f'{self.path.name} 외 {len(self.paths)-1}개 파일')
        self.columns.reset();self.columns.populate(sheets);self.mapping.reset();self.results.reset()
        self.finish_job();self.window.show_page(0)
        self.window.notice.set_message('파일을 열었어요. 회사 정보를 확인한 뒤 열 연결 설정을 눌러 주세요.')
    def inspect(self,header_row):
        if not self.path or self.window.busy:return
        self.window.set_busy(True,'선택한 행에서 열 이름을 다시 읽고 있어요.')
        self.jobs.start(lambda:inspect_workbook(self.path,header_row),self.headers_ready,self.failure)
    def headers_ready(self,sheets):
        self.finish_job();self.columns.populate(sheets);self.window.notice.set_message('열 이름을 다시 읽었어요. 연결할 열을 선택해 주세요.')
        if self.pending_preset:self.columns.apply_profile(self.pending_preset);self.pending_preset=None
    def current_profile(self):
        sheets,columns=self.columns.selections()
        profile=configure_profile(self.profile,self.home.company.text(),self.home.system.text(),sheets,columns,self.columns.header.value())
        profile['ledgerUnit']=self.home.unit.currentText()
        for key,field in (('periodStart',self.home.period_start),('periodEnd',self.home.period_end)):
            if field.text().strip():profile[key]=field.text().strip()
            else:profile.pop(key,None)
        return profile
    def load(self):
        if not self.path or self.window.busy:return
        sheets,columns=self.columns.selections()
        if not any(sheets.values()):self.window.notice.set_message('사용할 원장이나 재무상태표 시트를 하나 이상 선택해 주세요.',True);return
        try:profile=self.current_profile()
        except Exception as exc:self.window.notice.set_message(str(exc),True);return
        history_enabled=self.home.history.isChecked()
        self.window.set_busy(True,'자료를 읽고 계정별 후보를 정리하고 있어요.')
        self.jobs.start(lambda:load_batch(self.paths or [self.path],profile,self.catalog,history_enabled),self.session_ready,self.failure)
    def session_ready(self,session):
        self.session=session;self.window.has_session=True;self.finish_job()
        self.profile=session.profile
        if self.support_preset and not session.support_config:session.support_config=self.support_preset
        self.home.set_session(session);self.mapping.set_session(session,self.home.reviewer.text());self.results.set_session(session)
        self.window.show_page(2);counts=session.result['counts']
        self.window.notice.set_message(f"계정 후보를 불러왔어요. 미확정 {counts['pendingRows']:,}개 행과 오류 {counts['errors']:,}건을 확인해 주세요.")
    def review(self,target,decision,reviewer):
        if self.window.busy or not self.session or not self.mapping.editor.key:return
        key=self.mapping.editor.key
        self.window.set_busy(True,'선택한 계정 연결을 반영하고 있어요.')
        self.jobs.start(lambda:apply_review(self.session,key,target,decision,reviewer),self.review_ready,self.failure)
    def review_ready(self,session):
        self.session=session;self.finish_job();self.home.set_session(session);self.mapping.set_session(session,self.home.reviewer.text());self.results.set_session(session)
        self.window.notice.set_message('계정 연결을 반영했어요. 결과를 저장하면 확인·거절 이력도 보관해요.')
    def export(self):
        if not self.session or self.window.busy:return
        folder=QFileDialog.getExistingDirectory(self.window,'결과를 저장할 위치를 선택해 주세요',str(default_outputs().parent))
        if not folder:return
        self.window.set_busy(True,'검토 엑셀과 연결 데이터를 새 폴더에 저장하고 있어요.')
        self.jobs.start(lambda:export_session(self.session,folder),self.export_ready,self.failure)
    def export_ready(self,path):
        self.finish_job();self.results.exported(path);self.window.show_page(3);self.window.notice.set_message('검토 결과를 새 폴더에 저장했어요. 결과 폴더에서 파일을 열어 확인해 주세요.')
    def audit_export_ready(self,path):
        self.finish_job();self.results.exported(path);self.window.show_page(3)
        self.window.notice.set_message('통합감사 입력 엑셀을 저장했어요. 통합감사프로그램의 원장·리드에서 등록해 주세요.')
    def open_results(self):
        if self.results.output_path:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.results.output_path)))
    def open_report(self):
        if self.results.output_path:
            path=self.results.output_path/'검사결과.html'
            if path.is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def xbrl_export_ready(self,path):
        self.finish_job();self.results.exported(path);self.window.show_page(3)
        self.window.notice.set_message('XBRL GL XML을 저장했어요. 공식 스키마·행수·금액 확인 결과도 함께 보관했어요.')
    def cancel_xbrl_export(self):
        if self.window.busy and self.export_cancel:
            self.export_cancel.set();self.window.cancel_export.setEnabled(False)
            self.window.notice.set_message('XML 저장을 취소하고 있어요. 현재 업무는 그대로 유지해요.')
    def xbrl_export_cancelled(self):
        self.finish_job();self.window.notice.set_message('XML 저장을 취소했어요. 완료되지 않은 결과는 보관하지 않았어요.')
    def open_data(self):
        path=user_data();path.mkdir(parents=True,exist_ok=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def connect_support(self):
        if self.window.busy or not self.session:return
        dialog=SupportDialog(self.session,self.window)
        if not dialog.exec():return
        config=dialog.config();self.window.set_busy(True,'제공된 보조자료의 열과 금액을 읽고 있어요.')
        self.jobs.start(lambda:(prepare_support(config),config),self.support_ready,self.failure)
    def support_ready(self,value):
        bundle,config=value;self.session.support_bundle=bundle;self.session.support_config=config['tables'];self.session.support_setup=config;self.session.dirty=True
        self.finish_job();self.results.refresh_checks()
        self.window.notice.set_message('시산표 대사를 표시했어요. 차이는 원본 행에서 확인하고, 통제자료를 확인한 뒤 감사 입력을 저장해 주세요.')
    def failure(self,message,trace):
        self.pending_path=None;self.finish_job();self.window.notice.set_message(message or '자료를 읽는 중 문제가 생겼어요. 파일과 열 연결을 확인해 주세요.',True)
        folder=user_data()/'logs';folder.mkdir(parents=True,exist_ok=True)
        with (folder/'desktop.log').open('a',encoding='utf-8') as output:output.write(trace+'\n')
    def finish_job(self):
        self.export_cancel=None
        self.window.set_busy(False)
        if self.close_after_work:QTimer.singleShot(0,self.window.close)
    def can_close(self):
        filing=getattr(self,'_filing_dialog',None)
        if filing is not None:
            filing.raise_();filing.activateWindow();return False
        if self.force_close:return not self.window.busy
        if self.window.busy:
            if confirm(self.window,'작업을 마친 뒤 닫을까요?','현재 파일 처리를 마친 뒤 앱을 닫아요. 저장하지 않은 계정 연결은 닫으면 사라져요.','작업 후 앱 닫기'):
                self.close_after_work=True;self.force_close=True
            return False
        if self.session and self.session.dirty:
            return confirm(self.window,'앱을 닫을까요?','저장하지 않은 계정 연결이 있어요. 검토 엑셀로 저장한 뒤 이어서 작업할 수 있어요.','저장하지 않고 닫기')
        return True
