from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox,QLineEdit,QHBoxLayout
from .card import Card
from .text import label
from .buttons import button
from .badge import Badge

class ReviewEditor(Card):
    decisionRequested=Signal(str,str,str)
    def __init__(self):
        super().__init__('선택한 계정','왼쪽에서 계정을 선택하면 후보를 볼 수 있어요.')
        self.key=None
        self.name=label('검토할 계정을 선택해요','CardTitle',True);self.body.addWidget(self.name)
        self.original=label('','Muted',True);self.body.addWidget(self.original)
        self.candidates=label('계정명과 별칭을 비교해 후보를 제안해요.','Muted',True);self.body.addWidget(self.candidates)
        self.body.addWidget(label('연결할 표준 계정'));self.target=QComboBox();self.target.setMinimumWidth(235);self.body.addWidget(self.target)
        self.body.addWidget(label('확인자'));self.reviewer=QLineEdit();self.reviewer.setPlaceholderText('이름을 입력해 주세요');self.body.addWidget(self.reviewer)
        self.accept=button('이 계정으로 연결','primary');self.accept.clicked.connect(lambda:self.decide('확인'));self.body.addWidget(self.accept)
        other=QHBoxLayout();self.reject=button('이 후보 제외','danger');self.defer=button('나중에 검토');other.addWidget(self.reject);other.addWidget(self.defer);self.body.addLayout(other)
        self.reject.clicked.connect(lambda:self.decide('거절'));self.defer.clicked.connect(lambda:self.decide('미확정'))
        self.body.addWidget(label('점수는 추천 순서예요. 새 연결은 확인 후 적용해요.','Muted',True));self.body.addStretch()
        self.setEnabled(False)
    def decide(self,state):self.decisionRequested.emit(self.target.currentData() or '',state,self.reviewer.text())
    def set_account(self,row,catalog,reviewer=''):
        self.setEnabled(True);self.key=row['key'];self.name.setText(row['originalName'])
        self.original.setText(f"{row['company']} / {row['originalCode']}\n{row['transactionCount']:,}개 행 · {row['mappingStatus']}")
        details=row.get('candidateDetails',[])
        self.candidates.setText('\n\n'.join(f"{i+1}. {c['name']}  {c['score']:.2f}\n{c['reason']}" for i,c in enumerate(details)) or '일치하는 후보를 찾지 못했어요. 표준 계정을 직접 선택해 주세요.')
        self.target.clear();self.target.addItem('표준 계정을 선택해 주세요',None)
        for account in catalog['accounts']:
            if row['kind']=='원장' and account['kind']!='account':continue
            self.target.addItem(f"{account['code']}  {account['name']}",account['code'])
        code=row['standardCode'] or (details[0]['code'] if details else None)
        if code:self.target.setCurrentIndex(max(0,self.target.findData(code)))
        if reviewer and not self.reviewer.text():self.reviewer.setText(reviewer)
