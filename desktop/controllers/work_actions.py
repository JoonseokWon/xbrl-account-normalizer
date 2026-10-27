from pathlib import Path
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog
from application.workfiles import save_work,load_work
from application.presets import save_preset,load_preset
from application.catalogs import save_catalog,replace_session_catalog
from application.paths import default_outputs
from io_xlsx.inspection import inspect_workbook
from desktop.dialogs.catalog import CatalogDialog
from desktop.components.confirmation import confirm
from .xbrl_inspection import choose_and_inspect

class WorkActions:
    def __init__(self,controller):
        self.c=controller;menu=controller.window.menuBar().addMenu('업무')
        for title,callback in [('새 파일 열기',controller.choose_file),('저장한 업무 열기',self.open_work),('업무 저장',self.save_work),('저장한 XML 다시 검사',lambda:choose_and_inspect(controller)),('표준 계정 사전 관리',self.catalog)]:
            action=QAction(title,controller.window);action.triggered.connect(callback);menu.addAction(action)
        controller.columns.presetSaveRequested.connect(self.save_preset);controller.columns.presetLoadRequested.connect(self.load_preset)
    def error(self,error):self.c.window.notice.set_message(str(error),True)
    def can_replace(self):
        c=self.c
        return not c.window.busy and (not c.session or not c.session.dirty or confirm(c.window,'현재 업무를 바꿀까요?','저장하지 않은 변경이 있어요. 업무 저장으로 보관한 뒤 다시 열 수 있어요.','저장하지 않고 변경'))
    def save_work(self):
        c=self.c
        if c.window.busy:return
        if not c.session:self.error('자료를 불러온 뒤 업무를 저장해 주세요.');return
        filename=str(c.session.job_path or default_outputs()/'새업무.acwork')
        path,_=QFileDialog.getSaveFileName(c.window,'업무 저장',filename,'회계 표준화 업무 (*.acwork)')
        if not path:return
        if not path.lower().endswith('.acwork'):path+='.acwork'
        session=c.session;reviewer=c.home.reviewer.text()
        c.window.set_busy(True,'원본 파일과 검토 상태를 업무 파일에 보관하고 있어요.')
        c.jobs.start(lambda:save_work(session,path,reviewer),lambda p:self.saved(p),c.failure)
    def saved(self,path):
        self.c.finish_job();self.c.window.notice.set_message('업무를 저장했어요. 원본 파일과 계정 연결 상태를 함께 보관했어요.')
    def open_work(self):
        c=self.c
        if not self.can_replace():return
        path,_=QFileDialog.getOpenFileName(c.window,'저장한 업무 열기',str(default_outputs().parent),'회계 표준화 업무 (*.acwork)')
        if not path:return
        c.window.set_busy(True,'업무 원본의 무결성과 검토 상태를 확인하고 있어요.')
        def run():
            session=load_work(path);sheets=inspect_workbook(session.input_path,session.profile.get('headerRows',{}).get('gl',1));return session,sheets
        c.jobs.start(run,self.restored,c.failure)
    def restored(self,value):
        c=self.c;session,sheets=value;c.path=session.input_path;c.paths=list(session.input_paths);c.profile=session.profile;c.catalog=session.catalog
        c.pending_path=None;c.window.has_file=True;c.home.begin_file(c.path,True)
        c.home.company.setText(session.profile.get('companyCode') or '');c.home.system.setText(session.profile['sourceSystem'])
        c.home.reviewer.setText(getattr(session,'reviewer',''));c.home.history.setChecked(False)
        c.home.period_start.setText(session.profile.get('periodStart',''));c.home.period_end.setText(session.profile.get('periodEnd',''));c.home.unit.setCurrentText(session.profile['ledgerUnit'])
        c.columns.reset();c.columns.populate(sheets);c.columns.apply_profile(session.profile);c.session_ready(session)
        c.window.notice.set_message('업무를 다시 열었어요. 보관된 원본과 계정 검토 상태를 복원했어요.')
    def save_preset(self):
        c=self.c
        if c.window.busy:return
        try:
            profile=c.current_profile();support=c.session.support_config if c.session else {}
            save_preset(profile,support_config=support);c.window.notice.set_message('이 회사·원천시스템의 입력 설정을 저장했어요. 기간은 다음 업무에서 다시 입력해요.')
        except Exception as exc:self.error(exc)
    def load_preset(self):
        c=self.c
        if c.window.busy:return
        try:
            data=load_preset(c.home.company.text().strip(),c.home.system.text().strip());c.profile=data['profile'];c.columns.header.setValue(c.profile.get('headerRows',{}).get('gl',1))
            c.pending_preset=c.profile;c.support_preset=data.get('support',{});c.inspect(c.columns.header.value())
            c.home.unit.setCurrentText(c.profile['ledgerUnit'])
        except Exception as exc:self.error(exc)
    def catalog(self):
        c=self.c
        if c.window.busy:return
        dialog=CatalogDialog(c.catalog,c.window)
        if not dialog.exec():return
        try:
            value=dialog.value
            if c.session:replace_session_catalog(c.session,value)
            c.catalog=save_catalog(value)
            if c.session:c.session_ready(c.session)
            c.window.notice.set_message('표준 계정 사전을 저장했어요. 사전이 바뀐 계정 연결은 다시 확인해 주세요.')
        except Exception as exc:self.error(exc)
