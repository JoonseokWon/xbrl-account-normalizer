from .tokens import COLORS as C

def stylesheet():
    return f'''
    QWidget {{ font-family: "Noto Sans KR"; font-size: 13px; color: {C['text']}; }}
    QMainWindow, QWidget#Workspace {{ background: {C['background']}; }}
    QWidget#Page {{ background: transparent; }}
    QWidget#PageViewport {{ background: {C['background']}; }}
    QFrame#Sidebar {{ background: white; border-right: 1px solid {C['line']}; }}
    QFrame#Card {{ background: white; border: 1px solid {C['line']}; border-radius: 20px; }}
    QFrame#Card[emphasis="blue"] {{ background: #EEF4FF; border: 1px solid #DCE8FF; }}
    QLabel#PageTitle {{ font-size: 29px; font-weight: 700; letter-spacing: -1px; }}
    QLabel#CardTitle {{ font-size: 17px; font-weight: 700; }}
    QLabel#Muted {{ color: {C['muted']}; font-size: 12px; }}
    QLabel#MetricValue {{ font-size: 31px; font-weight: 700; }}
    QLabel#SectionLabel {{ color: {C['muted']}; font-size: 11px; font-weight: 700; }}
    QPushButton {{ min-height: 42px; padding: 0 18px; border-radius: 11px; border: none; background: #EDF1F6; font-weight: 600; }}
    QPushButton:hover {{ background: #E4EAF3; }}
    QPushButton:focus {{ border: 2px solid #90B5FF; }}
    QPushButton:disabled {{ background: #EDF1F6; color: #A0ABBA; }}
    QPushButton#Primary {{ background: {C['primary']}; color: white; }}
    QPushButton#Primary:hover {{ background: #1758DB; }}
    QPushButton#Primary:disabled {{ background: #DBE7FE; color: #91ACD9; }}
    QPushButton#Ghost {{ background: transparent; color: {C['primary']}; }}
    QPushButton#Ghost:hover {{ background: {C['primarySoft']}; }}
    QPushButton#Danger {{ background: {C['redSoft']}; color: {C['red']}; }}
    QPushButton#Nav {{ text-align: left; color: #637087; background: transparent; border-radius: 12px; padding: 0 18px; min-height: 46px; font-weight: 500; }}
    QPushButton#Nav:checked {{ background: {C['primarySoft']}; color: {C['primary']}; font-weight: 700; }}
    QPushButton#Nav:hover {{ background: #F0F4FA; }}
    QLineEdit, QComboBox, QSpinBox {{ background: #F7F9FC; border: 1px solid #E4EAF2; border-radius: 10px; padding: 10px 12px; min-height: 20px; selection-background-color: #D9E7FF; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {C['primary']}; background: white; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{ background: white; border: 1px solid #DDE5EF; selection-background-color: #EAF1FF; selection-color: #202B3D; }}
    QCheckBox {{ spacing: 9px; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; }}
    QTableView {{ background: white; border: none; gridline-color: #EDF1F6; selection-background-color: #EDF4FF; selection-color: #1E4A9A; alternate-background-color: #FAFBFD; }}
    QTableView::item {{ padding: 9px; border-bottom: 1px solid #F0F3F7; }}
    QHeaderView::section {{ background: #F7F9FC; border: none; border-bottom: 1px solid #E8EDF3; padding: 12px 10px; font-weight: 600; color: #68778C; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #CED7E3; border-radius: 4px; min-height: 32px; }}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height: 0; }}
    QTabWidget::pane {{ border: none; background: white; }}
    QTabBar::tab {{ padding: 10px 16px; margin-right: 5px; color: #778398; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {C['primary']}; border-bottom: 2px solid {C['primary']}; }}
    QProgressBar {{ border: none; background: #E5EDFA; border-radius: 3px; max-height: 5px; }}
    QProgressBar::chunk {{ background: {C['primary']}; border-radius: 3px; }}
    QToolTip {{ background: #23314B; color: white; border: none; padding: 8px; }}
    '''
