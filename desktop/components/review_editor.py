from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import (QComboBox,QLineEdit,QHBoxLayout,QLayout,QWidget,
    QVBoxLayout,QTabWidget,QScrollArea,QCompleter)
from .card import Card
from .text import label
from .buttons import button
from .badge import Badge
from .wrapping_label import WrappingLabel

class ReviewEditor(Card):
    decisionRequested=Signal(str,str,str)
    localLlmSettingsRequested=Signal()
    localLlmRequested=Signal()
    def __init__(self):
        super().__init__('선택한 계정','왼쪽에서 계정을 선택하면 후보를 볼 수 있어요.')
        self.key=None;self.llm_candidates=[]
        self.name=label('검토할 계정을 선택해요','CardTitle',True);self.body.addWidget(self.name)
        self.original=label('','Muted',True);self.body.addWidget(self.original)
        local=QHBoxLayout();self.llm_settings=button('로컬 LLM 설정');self.llm_request=button('후보 3개 추천')
        self.llm_settings.clicked.connect(self.localLlmSettingsRequested);self.llm_request.clicked.connect(self.localLlmRequested)
        local.addWidget(self.llm_settings);local.addWidget(self.llm_request);self.body.addLayout(local)
        self.candidate_tabs=QTabWidget();self.candidate_tabs.setMinimumHeight(190);self.candidate_tabs.setMaximumHeight(330)
        self.candidates=WrappingLabel('계정명과 별칭을 비교해 후보를 제안해요.');self.candidates.setObjectName('Muted')
        dictionary=QScrollArea();dictionary.setWidgetResizable(True);dictionary.setWidget(self.candidates)
        self.candidate_tabs.addTab(dictionary,'사전 후보')
        local_pane=QWidget();local_rows=QVBoxLayout(local_pane);local_rows.setContentsMargins(4,8,4,8)
        self.llm_status=WrappingLabel('로컬 모델을 설정한 뒤 후보 3개 추천을 눌러 주세요.');self.llm_status.setObjectName('Muted');local_rows.addWidget(self.llm_status)
        self.llm_buttons=[];self.llm_reasons=[]
        for index in range(3):
            choose=button('후보 선택');choose.clicked.connect(lambda checked=False,i=index:self.choose_llm_candidate(i));choose.hide()
            reason=WrappingLabel();reason.setObjectName('Muted');reason.hide()
            local_rows.addWidget(choose);local_rows.addWidget(reason);self.llm_buttons.append(choose);self.llm_reasons.append(reason)
        local_rows.addStretch()
        local_scroll=QScrollArea();local_scroll.setWidgetResizable(True);local_scroll.setWidget(local_pane)
        self.candidate_tabs.addTab(local_scroll,'로컬 LLM 후보');self.body.addWidget(self.candidate_tabs)
        self.body.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.body.addWidget(label('연결할 표준 계정 · 다른 계정도 직접 선택할 수 있어요'))
        self.target=QComboBox();self.target.setMinimumWidth(235);self.target.setEditable(True)
        self.target.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);self.target.setMaxVisibleItems(15)
        self.target.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.target.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.target.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.body.addWidget(self.target)
        self.body.addWidget(label('확인자'));self.reviewer=QLineEdit();self.reviewer.setPlaceholderText('이름을 입력해 주세요');self.body.addWidget(self.reviewer)
        self.accept=button('이 계정으로 연결','primary');self.accept.clicked.connect(lambda:self.decide('확인'));self.body.addWidget(self.accept)
        other=QHBoxLayout();self.reject=button('이 후보 제외','danger');self.defer=button('나중에 검토');other.addWidget(self.reject);other.addWidget(self.defer);self.body.addLayout(other)
        self.reject.clicked.connect(lambda:self.decide('거절'));self.defer.clicked.connect(lambda:self.decide('미확정'))
        self.body.addWidget(label('추천이나 후보 선택만으로 연결되지 않아요. 확인자를 입력하고 연결 버튼을 눌러 승인해 주세요.','Muted',True));self.body.addStretch()
        self.setEnabled(False)
    def selected_target(self):
        # An editable combo retains the old index while the user types. Never
        # approve that old account when the displayed text is only a fragment.
        text=self.target.currentText()
        index=self.target.findText(text,Qt.MatchFlag.MatchExactly)
        return self.target.itemData(index) if index>=0 else None
    def decide(self,state):self.decisionRequested.emit(self.selected_target() or '',state,self.reviewer.text())
    def set_llm_candidates(self,candidates):
        self.llm_candidates=list(candidates or [])
        valid=len(self.llm_candidates)==3
        self.llm_status.setText('세 후보를 비교한 뒤 하나를 고르거나 전체 계정에서 직접 선택해 주세요.' if valid else '아직 로컬 LLM 추천이 없어요. 모델을 설정한 뒤 후보 3개 추천을 눌러 주세요.')
        for i,(choose,reason) in enumerate(zip(self.llm_buttons,self.llm_reasons)):
            choose.setVisible(valid);reason.setVisible(valid)
            if valid:
                candidate=self.llm_candidates[i];choose.setText(f"{i+1}. {candidate['code']}  {candidate['name']} 선택")
                reason.setText(candidate.get('reason',''))
        if valid:self.candidate_tabs.setCurrentIndex(1)
    def choose_llm_candidate(self,index):
        if not 0<=index<len(self.llm_candidates):return
        code=self.llm_candidates[index].get('code')
        selected=self.target.findData(code)
        if selected>0:
            self.target.setCurrentIndex(selected)
            self.llm_status.setText('후보를 골랐어요. 계정과 확인자를 확인하고 이 계정으로 연결을 눌러 주세요.')
    def set_account(self,row,catalog,reviewer=''):
        self.setEnabled(True);self.key=row['key'];self.name.setText(row['originalName'])
        self.original.setText(f"{row['company']} / {row['originalCode']}\n{row['transactionCount']:,}개 행 · {row['mappingStatus']}")
        details=row.get('candidateDetails',[])
        self.candidates.setText('\n\n'.join(f"{i+1}. {c['name']}  {c['score']:.2f}\n{c['reason']}" for i,c in enumerate(details)) or '일치하는 후보를 찾지 못했어요. 표준 계정을 직접 선택해 주세요.')
        self.target.clear();self.target.addItem('표준 계정을 선택해 주세요',None)
        for account in catalog['accounts']:
            if row['kind']=='원장' and account['kind']!='account':continue
            if row['kind']=='재무제표' and account['statement']!='BS':continue
            self.target.addItem(f"{account['code']}  {account['name']}",account['code'])
        code=row['standardCode'] or (details[0]['code'] if details else None)
        if code:self.target.setCurrentIndex(max(0,self.target.findData(code)))
        self.set_llm_candidates(row.get('llmCandidates',[]))
        if reviewer and not self.reviewer.text():self.reviewer.setText(reviewer)
