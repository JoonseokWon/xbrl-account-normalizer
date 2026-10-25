from pathlib import Path
from PySide6.QtCore import QObject,QUrl,QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog
from application.configuration import default_profile,default_catalog,configure_profile
from application.loading import load_session
from application.reviews import apply_review
from application.exporting import export_session
from application.paths import user_data,default_outputs
from io_xlsx.inspection import inspect_workbook
from .jobs import Jobs
from desktop.components.confirmation import confirm

class AppController(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.jobs=Jobs();self.path=None;self.pending_path=None;self.session=None;self.profile=default_profile();self.catalog=default_catalog();self.close_after_work=False;self.force_close=False
        window.close_guard=self.can_close
        self.home,self.columns,self.mapping,self.results,self.help=window.pages
        self.home.chooseRequested.connect(self.choose_file);self.home.fileDropped.connect(self.open_file)
        window.fileRequested.connect(self.choose_file)
        self.columns.inspectRequested.connect(self.inspect)
        self.columns.loadRequested.connect(self.load);self.mapping.resultsRequested.connect(lambda:window.show_page(3))
        self.mapping.editor.decisionRequested.connect(self.review)
        self.results.exportRequested.connect(self.export);self.results.openFolderRequested.connect(self.open_results)
        self.help.openDataRequested.connect(self.open_data);window.actionRequested.connect(self.action)
    def action(self,index):
        if self.window.busy:return
        if index==0:
            if self.window.has_file:self.window.show_page(1)
            else:self.choose_file()
        elif index==1:self.load()
        elif index==2:self.window.show_page(3)
        elif index==3:self.export()
    def choose_file(self):
        if self.window.busy:return
        folder=self.path.parent if self.path else Path.home()/'Documents'
        path,_=QFileDialog.getOpenFileName(self.window,'새 작업에 사용할 엑셀 파일을 선택해 주세요',str(folder),'엑셀 통합문서 (*.xlsx)')
        if path:self.open_file(path)
    def open_file(self,path):
        if self.window.busy:return
        if self.session and self.session.dirty:
            if not confirm(self.window,'새 파일로 작업을 시작할까요?','저장하지 않은 계정 연결이 있어요. 새 파일을 열면 현재 작업과 회사 정보를 바꿔요.','새 파일 열기'):return
        selected=Path(path);self.pending_path=selected
        self.window.set_busy(True,'엑셀의 시트와 열 이름을 읽고 있어요.')
        self.jobs.start(lambda:inspect_workbook(selected,1),self.file_ready,self.failure)
    def file_ready(self,sheets):
        previous=self.path;self.path=self.pending_path;self.pending_path=None;self.session=None
        self.window.has_file=True;self.window.has_session=False
        self.home.begin_file(self.path,reset_details=previous is not None)
        self.columns.reset();self.columns.populate(sheets);self.mapping.reset();self.results.reset()
        self.finish_job();self.window.show_page(0)
        self.window.notice.set_message('파일을 열었어요. 회사 정보를 확인한 뒤 열 연결 설정을 눌러 주세요.')
    def inspect(self,header_row):
        if not self.path or self.window.busy:return
        self.window.set_busy(True,'선택한 행에서 열 이름을 다시 읽고 있어요.')
        self.jobs.start(lambda:inspect_workbook(self.path,header_row),self.headers_ready,self.failure)
    def headers_ready(self,sheets):
        self.finish_job();self.columns.populate(sheets);self.window.notice.set_message('열 이름을 다시 읽었어요. 연결할 열을 선택해 주세요.')
    def load(self):
        if not self.path or self.window.busy:return
        sheets,columns=self.columns.selections()
        if not any(sheets.values()):self.window.notice.set_message('사용할 원장이나 재무상태표 시트를 하나 이상 선택해 주세요.',True);return
        profile=configure_profile(self.profile,self.home.company.text(),self.home.system.text(),sheets,columns,self.columns.header.value())
        history_enabled=self.home.history.isChecked()
        self.window.set_busy(True,'자료를 읽고 계정별 후보를 정리하고 있어요.')
        self.jobs.start(lambda:load_session(self.path,profile,self.catalog,history_enabled),self.session_ready,self.failure)
    def session_ready(self,session):
        self.session=session;self.window.has_session=True;self.finish_job()
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
    def open_results(self):
        if self.results.output_path:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.results.output_path)))
    def open_data(self):
        path=user_data();path.mkdir(parents=True,exist_ok=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def failure(self,message,trace):
        self.pending_path=None;self.finish_job();self.window.notice.set_message(message or '자료를 읽는 중 문제가 생겼어요. 파일과 열 연결을 확인해 주세요.',True)
        folder=user_data()/'logs';folder.mkdir(parents=True,exist_ok=True)
        with (folder/'desktop.log').open('a',encoding='utf-8') as output:output.write(trace+'\n')
    def finish_job(self):
        self.window.set_busy(False)
        if self.close_after_work:QTimer.singleShot(0,self.window.close)
    def can_close(self):
        if self.force_close:return not self.window.busy
        if self.window.busy:
            if confirm(self.window,'작업을 마친 뒤 닫을까요?','현재 파일 처리를 마친 뒤 앱을 닫아요. 저장하지 않은 계정 연결은 닫으면 사라져요.','작업 후 앱 닫기'):
                self.close_after_work=True;self.force_close=True
            return False
        if self.session and self.session.dirty:
            return confirm(self.window,'앱을 닫을까요?','저장하지 않은 계정 연결이 있어요. 검토 엑셀로 저장한 뒤 이어서 작업할 수 있어요.','저장하지 않고 닫기')
        return True
