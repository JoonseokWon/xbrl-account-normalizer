"""Run local recommendations in the normal background-job lifecycle."""
from PySide6.QtCore import QObject,Qt
from threading import Event
from core.errors import InputError


class LocalLlmController(QObject):
    def __init__(self,controller):
        super().__init__(controller);self.controller=controller
        self.settings=None
        self.batch_cancel=None
        editor=controller.mapping.editor
        editor.localLlmSettingsRequested.connect(self.configure)
        editor.localLlmRequested.connect(self.recommend)
        controller.mapping.localLlmBatchRequested.connect(self.recommend_pending)
        controller.window.cancelRequested.connect(self.cancel_batch)

    def read_settings(self):
        if self.settings is None:
            from application.local_llm import load_settings
            self.settings=load_settings()
        return self.settings

    def refresh_recommendations(self):
        """A recommendation must not replace an unapproved human choice."""
        app=self.controller;editor=app.mapping.editor
        key,text,reviewer=editor.key,editor.target.currentText(),editor.reviewer.text()
        app.mapping.set_session(app.session,app.home.reviewer.text())
        if editor.key==key:
            index=editor.target.findText(text,Qt.MatchFlag.MatchExactly)
            if index>=0:editor.target.setCurrentIndex(index)
            else:editor.target.setEditText(text)
            editor.reviewer.setText(reviewer)

    def configure(self):
        app=self.controller
        if app.window.busy:return
        from desktop.dialogs.local_llm import LocalLlmSettingsDialog
        try:dialog=LocalLlmSettingsDialog(self.read_settings(),app.window)
        except Exception as error:app.window.notice.set_message(str(error),True);return
        if not dialog.exec():return
        self.settings=dialog.settings
        if app.session:
            from application.llm_mapping import set_session_settings
            set_session_settings(app.session,self.settings)
            self.refresh_recommendations()
        app.window.notice.set_message('로컬 LLM 설정을 저장했어요. 계정을 선택하고 후보 3개 추천을 눌러 주세요.')

    def recommend(self):
        app=self.controller
        if app.window.busy or app.session is None or not app.mapping.editor.key:return
        from application.llm_mapping import request_mapping,apply_recommendations,set_session_settings
        try:
            settings=dict(self.read_settings())
            set_session_settings(app.session,settings)
        except Exception as error:app.window.notice.set_message(str(error),True);return
        session=app.session;key=app.mapping.editor.key
        app.window.set_busy(True,'로컬 모델이 이 계정의 후보 3개를 추천하고 있어요. 연결은 승인 후 적용돼요.')
        def work():
            envelope=request_mapping(session,key,settings)
            apply_recommendations(session,envelope,settings=settings)
            return session
        def ready(result):
            try:
                if app.session is not session or self.settings!=settings:raise InputError('추천을 요청한 업무나 모델이 바뀌었어요. 현재 업무에서 다시 추천해 주세요.')
                self.refresh_recommendations()
                app.mapping.editor.candidate_tabs.setCurrentIndex(1)
                app.window.notice.set_message('로컬 LLM 후보 3개를 준비했어요. 하나를 고르거나 다른 계정을 직접 선택한 뒤 확인자를 입력하고 연결을 승인해 주세요.')
            except Exception as error:app.window.notice.set_message(str(error),True)
            finally:app.finish_job()
        app.jobs.start(work,ready,self.failure)

    def failure(self,message,trace=''):
        app=self.controller;self.batch_cancel=None;app.window.cancel_export.setText('XML 저장 취소');app.finish_job()
        app.window.notice.set_message((str(message) or '로컬 LLM 추천을 받지 못했어요.')+' 사전 후보와 직접 선택으로 계속 검토할 수 있어요.',True)

    def recommend_pending(self):
        app=self.controller
        if app.window.busy or app.session is None:return
        from application.llm_mapping import request_pending_mappings,set_session_settings
        try:
            settings=dict(self.read_settings());set_session_settings(app.session,settings)
        except Exception as error:app.window.notice.set_message(str(error),True);return
        session=app.session;self.batch_cancel=Event();cancel=self.batch_cancel
        app.window.set_busy(True,'미확정 계정 중 아직 추천이 없는 계정을 최대 20개씩 추천하고 있어요.')
        app.window.cancel_export.setText('로컬 추천 중단');app.window.cancel_export.setEnabled(True);app.window.cancel_export.show()
        def work(progress):
            return request_pending_mappings(session,settings,limit=20,progress=progress,cancel_event=cancel)
        def progress(value):
            completed,total=value.get('completed',0),value.get('total',0)
            app.window.progress.setRange(0,max(1,total));app.window.progress.setValue(completed)
            if not cancel.is_set():app.window.notice.set_message(f'로컬 LLM 계정 추천 · {completed:,} / {total:,}개 · 승인은 별도로 확인해 주세요.')
        def ready(result):
            self.batch_cancel=None;app.window.cancel_export.setText('XML 저장 취소')
            try:
                if app.session is not session or self.settings!=settings:raise InputError('추천 중 업무나 모델이 바뀌었어요. 현재 업무에서 다시 요청해 주세요.')
                self.refresh_recommendations();app.mapping.editor.candidate_tabs.setCurrentIndex(1)
                successes=result.get('succeeded',result.get('completed',0));errors=result.get('errors',[])
                details=[f"추천 {successes:,}개 · 기존 추천 유지 {result.get('skipped',0):,}개 · 실패 {len(errors):,}개 · 남은 계정 {result.get('remaining',0):,}개"]
                details.extend(f"{item.get('sourceName','계정')}: {item.get('message','추천하지 못했어요.')}" for item in errors)
                app.mapping.llm_batch_report.setPlainText('\n'.join(details));app.mapping.llm_batch_report.show()
                message=f'로컬 추천 {successes:,}개를 준비했어요. 각 계정의 후보를 선택하고 연결을 승인해 주세요.'
                if result.get('cancelled'):message=f'현재 계정까지 마치고 중단했어요. 준비된 추천 {successes:,}개와 기존 연결은 유지했어요.'
                if errors:message+=f' 추천하지 못한 계정 {len(errors):,}개는 직접 검토하거나 다시 요청해 주세요.'
                if not result.get('total',0):message='새로 추천할 미확정 계정이 없어요. 기존 후보를 검토하거나 선택한 계정을 다시 추천해 주세요.'
                app.window.notice.set_message(message)
            except Exception as error:app.window.notice.set_message(str(error),True)
            finally:app.finish_job()
        app.jobs.start_progress(work,ready,self.failure,progress,lambda:self.failure('로컬 추천을 중단했어요.'))

    def cancel_batch(self):
        if self.batch_cancel is None:return
        self.batch_cancel.set();app=self.controller
        app.window.cancel_export.setEnabled(False)
        app.window.notice.set_message('현재 계정의 추천을 마친 뒤 중단해요. 준비한 추천과 기존 연결은 유지해요.')
