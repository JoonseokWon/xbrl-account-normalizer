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
        sections=[('회사별 파일을 선택해요','같은 회사·양식의 XLSX 또는 CSV·TSV 파일을 선택해요. 여러 월의 파일도 함께 열 수 있어요. 회사·기간·금액 단위를 확인하고 시트와 열을 연결해 주세요.'),
                  ('새 연결은 직접 확인해요','후보 점수는 계정명 유사도예요. 연결할 계정을 선택하고 확인자 이름을 입력하면 적용해요.'),
                  ('업무를 저장하고 다시 열어요','상단 업무 메뉴에서 원본·사전·검토 상태를 .acwork로 보관해요. 보조자료를 열 연결로 가져왔다면 해당 원본도 함께 보관해요.'),
                  ('전표와 대사를 확인해요','변환 결과에서 전표별 차변·대변과 원본 행을 확인해요. 회사 양식의 시산표·별도 통제를 열로 연결하고 대사를 확인한 뒤 감사 입력을 저장해요.'),
                  ('입력 설정과 사전을 관리해요','같은 회사·ERP의 열 연결은 저장해 다시 사용해요. 업무 메뉴에서 표준 계정 사전을 수정할 수 있고, 변경된 계정 연결은 재확인해요.'),
                  ('큰 원장도 넘길 수 있어요','파일당 10만 행, 업무당 25만 행까지 처리하고 큰 원장은 통합감사 v2.3 이상으로 넘겨요. 원장을 임의로 분할하지 않아요. 공식 XBRL GL 출력은 아직 지원하지 않아요.')]
        for i,(title,text) in enumerate(sections):
            card=Card(title);card.body.addWidget(label(text,wrap=True));card.body.addStretch();card.setMinimumHeight(175);grid.addWidget(card,i//2,i%2)
        root.addLayout(grid)
        storage=Card('연결 이력과 기록');storage.body.addWidget(label('이 컴퓨터에 승인·거절 이력과 오류 기록을 보관해요. 다른 회사나 시스템의 승인 이력은 자동 적용하지 않아요.','Muted',True))
        open_data=button('로컬 기록 폴더 열기');open_data.clicked.connect(self.openDataRequested);storage.body.addWidget(open_data);root.addWidget(storage);root.addStretch()
