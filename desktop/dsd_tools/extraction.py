from pathlib import Path
from desktop.components.buttons import button
from desktop.components.text import label
from .common import Panel, path_row, save_path, output_name, DSD_FILTER, XLSX_FILTER


class ExtractPanel(Panel):
    def __init__(self, owner):
        super().__init__(owner, '공시문서의 표를 엑셀로 가져와요',
                         '표별 시트에 숫자·문구·병합 위치를 보존해요. 원본 위치도 함께 기록하므로 수정본을 같은 DSD 양식에 다시 반영할 수 있어요.')
        row, self.source = path_row(self, 'DSD 파일 선택', DSD_FILTER)
        self.body.addWidget(row)
        self.body.addWidget(label('공란·대시·0을 구분해요. 원본에 없는 합계나 당기·전기 전환은 자동으로 만들지 않아요.', 'Muted', True))
        self.export_button = button('엑셀로 저장', 'primary'); self.export_button.clicked.connect(self.export)
        self.body.addWidget(self.export_button)
        self.result = label('먼저 공시문서 파일을 선택해 주세요.', 'Muted', True)
        self.body.addWidget(self.result); self.body.addStretch()

    def export(self):
        source = self.source.text()
        if not source:
            self.notice('DSD 파일을 먼저 선택해 주세요.'); return
        path = save_path(self, 'DSD 표 엑셀 저장', output_name(source, '_표.xlsx'), XLSX_FILTER)
        if path:
            self.export_to(path)

    def export_to(self, path):
        source = self.source.text()
        from xbrl_filing.dsd_excel import export_dsd_excel
        def done(report):
            self.result.setText('저장한 파일: ' + Path(path).name + '\n' + '\n'.join(report.get('warnings', [])))
            self.owner.last_export = report
            self.notice('엑셀 저장이 끝났어요. 표 시트를 수정하고 4번 화면에서 같은 DSD 양식에 반영할 수 있어요.')
        self.run(lambda: export_dsd_excel(source, path), done, 'DSD 표를 엑셀로 옮기고 원본 위치를 확인하고 있어요.')
