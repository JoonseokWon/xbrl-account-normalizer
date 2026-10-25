from PySide6.QtWidgets import QLabel
from desktop.theme.tokens import COLORS, TYPE

class Badge(QLabel):
    def __init__(self,text,tone='blue'):
        super().__init__(text)
        self.set_tone(tone)
        self.setMaximumHeight(34)
    def set_tone(self,tone):
        colors={'blue':('#EAF1FF','#246BFD'),'green':('#E9F7F1','#148565'),'amber':('#FFF4DC','#A66A0A'),'neutral':('#EDF1F6',COLORS['muted'])}
        bg,fg=colors.get(tone,colors['blue'])
        self.setStyleSheet(f'background:{bg};color:{fg};border-radius:8px;padding:5px 10px;font-size:{TYPE["badge"]}pt;font-weight:700;')
