from PySide6.QtCore import Signal,Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QStackedWidget,QScrollArea,QProgressBar
from desktop.components.sidebar import Sidebar
from desktop.components.text import label
from desktop.components.buttons import button
from desktop.components.badge import Badge
from desktop.components.notice import Notice
from desktop.screens.overview import OverviewScreen
from desktop.screens.columns import ColumnsScreen
from desktop.screens.mapping import MappingScreen
from desktop.screens.results import ResultsScreen
from desktop.screens.help import HelpScreen
from application.paths import resources

TITLES=[('자료 파일로 업무를 시작해요','회사·기간을 확인하고 원본 열을 연결해 주세요.'),
        ('원본의 열을 연결해요','원장과 재무상태표에서 사용할 열을 선택해 주세요.'),
        ('계정 연결을 확인해요','후보의 근거를 보고 연결할 표준 계정을 정해요.'),
        ('변환 결과를 살펴봐요','원본 코드와 검토 내용을 함께 저장할 수 있어요.'),
        ('필요한 내용을 확인해요','파일 준비부터 결과 저장까지 순서대로 안내해요.')]

class MainWindow(QMainWindow):
    actionRequested=Signal(int)
    fileRequested=Signal()
    def __init__(self,profile):
        super().__init__();self.setWindowTitle('회계데이터 표준화');self.setWindowIcon(QIcon(str(resources()/'assets/app-icon.svg')))
        self.resize(1420,960);self.setMinimumSize(1070,740);self.busy=False;self.has_file=False;self.has_session=False;self.close_guard=None
        central=QWidget();row=QHBoxLayout(central);row.setContentsMargins(0,0,0,0);row.setSpacing(0)
        self.sidebar=Sidebar();row.addWidget(self.sidebar)
        workspace=QWidget();workspace.setObjectName('Workspace');main=QVBoxLayout(workspace);main.setContentsMargins(30,27,30,25);main.setSpacing(18);row.addWidget(workspace,1)
        header=QHBoxLayout();texts=QVBoxLayout();texts.setSpacing(9);self.title=label('','PageTitle',True);self.subtitle=label('','Muted',True);texts.addWidget(self.title);texts.addWidget(self.subtitle);header.addLayout(texts,1)
        self.new_file=button('새 파일 열기');self.new_file.clicked.connect(self.fileRequested);header.addWidget(self.new_file)
        header.addWidget(Badge('미리보기','neutral'));self.action=button('열 연결 설정','primary');self.action.clicked.connect(lambda:self.actionRequested.emit(self.stack.currentIndex()));header.addWidget(self.action);main.addLayout(header)
        self.notice=Notice();main.addWidget(self.notice)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setTextVisible(False);self.progress.hide();main.addWidget(self.progress)
        self.stack=QStackedWidget();self.pages=[OverviewScreen(),ColumnsScreen(profile),MappingScreen(),ResultsScreen(),HelpScreen()]
        for page in self.pages:
            page.setObjectName('Page')
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.stack.addWidget(scroll)
            scroll.viewport().setObjectName('PageViewport')
        main.addWidget(self.stack,1);self.setCentralWidget(central)
        self.sidebar.pageRequested.connect(self.show_page);self.show_page(0)
    def show_page(self,index):
        if index==1 and not self.has_file:
            self.notice.set_message('먼저 엑셀 파일을 선택해 주세요.');return
        if index in (2,3) and not self.has_session:
            self.notice.set_message('열을 연결하고 계정 후보를 먼저 불러와 주세요.');return
        self.stack.setCurrentIndex(index);self.sidebar.select(index)
        self.title.setText(TITLES[index][0]);self.subtitle.setText(TITLES[index][1])
        self.refresh_action()
    def refresh_action(self):
        index=self.stack.currentIndex();texts=['열 연결 설정','계정 후보 불러오기','변환 결과 보기','검토 엑셀 저장','']
        if index==0 and not self.has_file:texts[0]='새 파일 열기'
        self.action.setText(texts[index]);self.action.setVisible(index!=4)
        self.action.setEnabled(not self.busy and (True if index==0 else self.has_file if index==1 else self.has_session))
        self.new_file.setVisible(index!=0 or self.has_file);self.new_file.setEnabled(not self.busy)
    def set_busy(self,busy,message=''):
        self.busy=busy;self.progress.setVisible(busy)
        for page in self.pages:page.setEnabled(not busy)
        self.refresh_action()
        if message:self.notice.set_message(message)
    def closeEvent(self,event):
        if self.close_guard and not self.close_guard():event.ignore()
        else:event.accept()
