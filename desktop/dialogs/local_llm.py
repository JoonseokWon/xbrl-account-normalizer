"""Configure an existing local Ollama model, without downloading weights."""
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
    QLineEdit,QComboBox,QSpinBox,QProgressBar)

from desktop.components.buttons import button
from desktop.components.text import label
from desktop.controllers.jobs import Jobs


class LocalLlmSettingsDialog(QDialog):
    def __init__(self,settings=None,parent=None,settings_path=None):
        super().__init__(parent)
        from application.local_llm import load_settings
        self.settings=dict(settings if settings is not None else load_settings(settings_path))
        self.settings_path=settings_path;self.loading=False;self.jobs=Jobs();self.models=[]
        self.setWindowTitle('로컬 LLM 계정 추천 설정');self.resize(730,520)
        root=QVBoxLayout(self);root.setSpacing(16)
        root.addWidget(label('이 컴퓨터의 모델로 계정 후보를 추천해요','PageTitle',True))
        root.addWidget(label('Ollama에서 실행 중인 로컬 서버와 설치한 모델을 선택해 주세요. 이 화면에서 모델을 내려받거나 외부 AI 서버에 연결하지 않아요.','Muted',True))
        self.fields=QWidget();form=QFormLayout(self.fields);form.setContentsMargins(0,0,0,0)
        self.endpoint=QLineEdit(self.settings.get('endpoint','http://127.0.0.1:11434'))
        self.endpoint.setPlaceholderText('http://127.0.0.1:11434')
        self.model=QComboBox();self.model.setMinimumWidth(300)
        if self.settings.get('model'):self.model.addItem(self.settings['model'],self.settings['model'])
        self.timeout=QSpinBox();self.timeout.setRange(5,300);self.timeout.setSuffix('초')
        self.timeout.setValue(int(self.settings.get('timeout',120)))
        form.addRow('로컬 서버 주소',self.endpoint);form.addRow('설치한 모델',self.model);form.addRow('추천 대기 시간',self.timeout)
        root.addWidget(self.fields)
        self.read_button=button('연결 확인 · 설치 모델 읽기');self.read_button.clicked.connect(self.read_models);root.addWidget(self.read_button)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setTextVisible(False);self.progress.hide();root.addWidget(self.progress)
        self.notice=label('이 컴퓨터의 설치 모델만 사용할 수 있어요. 먼저 연결을 확인해 주세요.','Muted',True);root.addWidget(self.notice)
        root.addWidget(label('추천에는 계정코드·계정명과 표준 계정 사전만 사용해요. 원장 전체·거래 금액·거래처 정보는 보내지 않아요. 추천 결과는 사람이 승인해야 연결돼요.','Muted',True))
        root.addStretch();commands=QHBoxLayout();commands.addStretch()
        self.cancel_button=button('닫기');self.cancel_button.clicked.connect(self.reject);commands.addWidget(self.cancel_button)
        self.save_button=button('설정 저장','primary');self.save_button.clicked.connect(self.save);commands.addWidget(self.save_button);root.addLayout(commands)
        self.endpoint.textChanged.connect(self.endpoint_changed)

    def endpoint_changed(self,*args):
        self.models=[];self.model.clear()
        self.notice.setText('주소가 바뀌었어요. 연결 확인으로 설치 모델을 다시 읽어 주세요.')

    def read_models(self):
        if self.loading:return
        from application.local_llm import list_models
        endpoint=self.endpoint.text().strip();previous=self.model.currentData()
        self.loading=True;self.fields.setEnabled(False);self.read_button.setEnabled(False);self.save_button.setEnabled(False);self.progress.show()
        self.notice.setText('로컬 서버와 실제 설치한 모델을 확인하고 있어요.')
        self.jobs.start(lambda:list_models(endpoint,timeout=5),lambda models:self.models_ready(models,previous),self.failure)

    def finish(self):
        self.loading=False;self.fields.setEnabled(True);self.read_button.setEnabled(True);self.save_button.setEnabled(True);self.progress.hide()

    def models_ready(self,models,previous=None):
        self.finish();self.models=list(models);self.model.clear()
        for item in self.models:self.model.addItem(item['name'],item['name'])
        if previous and self.model.findData(previous)>=0:self.model.setCurrentIndex(self.model.findData(previous))
        self.notice.setText(f'설치한 로컬 모델 {len(self.models)}개를 확인했어요. 사용할 모델을 선택해 주세요.' if self.models else '사용할 로컬 모델이 없어요. Ollama에 모델을 설치한 뒤 다시 읽어 주세요.')

    def failure(self,message,trace=''):
        self.finish();self.models=[];self.model.clear()
        self.notice.setText(str(message) or '로컬 서버에 연결하지 못했어요. Ollama 실행 상태와 주소를 확인해 주세요.')

    def save(self):
        if self.loading:return
        from application.local_llm import normalize_settings,save_settings
        try:
            model=self.model.currentData()
            if not model:raise ValueError('연결을 확인하고 설치한 모델을 선택해 주세요.')
            settings=normalize_settings({'endpoint':self.endpoint.text().strip(),'model':model,'timeout':self.timeout.value()})
            save_settings(settings,self.settings_path);self.settings=settings
        except Exception as error:self.notice.setText(str(error));return
        super().accept()

    def reject(self):
        if self.loading:self.notice.setText('로컬 모델 확인을 마친 뒤 닫을 수 있어요.');return
        super().reject()

    def closeEvent(self,event):
        if self.loading:event.ignore();self.notice.setText('로컬 모델 확인을 마친 뒤 닫을 수 있어요.')
        else:event.accept()
