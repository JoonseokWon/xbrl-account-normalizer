from PySide6.QtWidgets import QWidget,QVBoxLayout,QGridLayout
from desktop.components.card import Card
from desktop.components.text import label
from desktop.components.buttons import button
from application.paths import user_data
from PySide6.QtCore import Signal

class HelpScreen(QWidget):
    openDataRequested=Signal()
    def __init__(self):
        super().__init__();root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        grid=QGridLayout();grid.setSpacing(18)
        sections=[('새 파일 열기로 시작해요','회사별 원장이나 재무상태표 .xlsx를 선택해요. 회사 정보를 확인하고 열 연결 설정에서 시트와 열을 고른 뒤 계정 후보를 불러와 주세요.'),
                  ('새 연결은 직접 확인해요','후보 점수는 계정명 유사도예요. 연결할 계정을 선택하고 확인자 이름을 입력하면 적용해요.'),
                  ('원본은 그대로 보관해요','앱은 입력 파일을 덮어쓰지 않아요. 검토 결과는 선택한 위치의 새 폴더에 저장해요.'),
                  ('통합감사 입력으로 저장해요','계정 연결을 마치면 시산표·통제 보조파일과 함께 원장·리드용 입력 엑셀을 만들어요. 공식 XBRL GL 출력은 아직 지원하지 않아요.')]
        for i,(title,text) in enumerate(sections):
            card=Card(title);card.body.addWidget(label(text,wrap=True));card.body.addStretch();card.setMinimumHeight(175);grid.addWidget(card,i//2,i%2)
        root.addLayout(grid)
        storage=Card('연결 이력과 기록');storage.body.addWidget(label('이 컴퓨터에 승인·거절 이력과 오류 기록을 보관해요. 다른 회사나 시스템의 승인 이력은 자동 적용하지 않아요.','Muted',True))
        open_data=button('로컬 기록 폴더 열기');open_data.clicked.connect(self.openDataRequested);storage.body.addWidget(open_data);root.addWidget(storage);root.addStretch()
