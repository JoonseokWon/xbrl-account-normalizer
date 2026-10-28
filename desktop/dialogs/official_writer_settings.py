"""Explicit bilingual company/report metadata for the official importer."""
from datetime import date,datetime,timezone,timedelta
import re
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QDialogButtonBox,QScrollArea,QWidget
from desktop.components.text import label


class WriterSettingsDialog(QDialog):
    def __init__(self,report,parent=None):
        super().__init__(parent);self.setWindowTitle('작성기 불러오기 설정');self.resize(800,760);self.value=None
        root=QVBoxLayout(self);root.addWidget(label('회사·공시 서식을 확인해 주세요.','CardTitle',True))
        root.addWidget(label('공식 GCD 항목을 만드는 설정이에요. 영문 회사명과 서식 코드는 회사가 정한 값으로 입력해 주세요.','Muted',True))
        pane=QWidget();form=QFormLayout(pane);self.fields={}
        entity=report.get('entity',{});reporting=report.get('reporting',{});prior=report.get('officialWriterSettings',{})
        choices={'사업보고서':'Annual Report','1분기보고서':'First Quarterly Report','반기보고서':'Half Year Report','3분기보고서':'Third Quarterly Report'}
        self.title=QComboBox();self.title.addItems(list(choices));self.title.setCurrentText(prior.get('documentTitle','사업보고서'));form.addRow('보고서 종류',self.title)
        for index in range(1,self.title.count()):self.title.model().item(index).setEnabled(False)
        form.addRow('',label('연동 시험 XML은 사업보고서 형식만 지원해요. 분기·반기 보고서는 아직 지원하지 않아요.','Muted',True))
        definitions=[('companyName','회사명',entity.get('name','')),('companyNameEn','영문 회사명',prior.get('companyNameEn','')),
            ('centralIndexKey','회사고유번호 (8자리)',entity.get('identifier','')),('documentCreationDate','문서 작성일',prior.get('documentCreationDate',datetime.now(timezone(timedelta(hours=9))).date().isoformat())),
            ('ordinalYear','기수',prior.get('ordinalYear','')),('reviewer','설정 확인자',prior.get('reviewer',next((f.get('reviewer','') for f in report.get('facts',[]) if f.get('reviewer')),'')))]
        for key,title,value in definitions:
            field=QLineEdit(str(value));self.fields[key]=field;form.addRow(title,field)
        self.periods={}
        for key,title in (('priorPeriod','전기'),('secondPriorPeriod','전전기')):
            previous=prior.get(key,{}) if isinstance(prior.get(key,{}),dict) else {};self.periods[key]={}
            for boundary,caption in (('start','시작일'),('end','종료일')):
                field=QLineEdit(str(previous.get(boundary,'')));field.setPlaceholderText('YYYY-MM-DD')
                self.periods[key][boundary]=field;form.addRow(title+' '+caption,field)
        form.addRow('',label('전기·전전기의 실제 보고기간을 입력해 주세요. 날짜를 자동으로 추정하지 않아요.','Muted',True))
        self.forms={}
        examples={'BS':'D1001: 유동·비유동 구분','PL':'D2001: 일괄·기능별·세후 포괄손익','CE':'D3001: 자본변동표','CF':'D4002: 간접법'}
        for key in ('BS','PL','CE','CF'):
            field=QLineEdit(prior.get('formCodes',{}).get(key,''));field.setPlaceholderText('확인된 예: '+examples[key]);self.forms[key]=field;form.addRow(key+' 서식 코드',field)
        form.addRow('보고 기간',label(str(reporting.get('periodStart',''))+' ~ '+str(reporting.get('periodEnd','')),wrap=True))
        form.addRow('연결/별도',label(str(reporting.get('consolidation','')),wrap=True))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(pane);root.addWidget(scroll,1)
        self.notice=label('값은 기존 승인 입력의 회사·기간과 일치해야 해요. 만들어진 후보 파일의 공식 불러오기와 최종 생성은 별도 확인합니다.','Muted',True);root.addWidget(self.notice)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('확인 후 파일 준비');buttons.accepted.connect(self.accept_settings);buttons.rejected.connect(self.reject);root.addWidget(buttons)
        self.report=report;self.titles=choices
    def accept_settings(self):
        self.value=None
        values={key:field.text().strip() for key,field in self.fields.items()}
        if any(not value for value in values.values()) or any(not f.text().strip() for f in self.forms.values()):self.notice.setText('회사·보고서·확인자·서식 코드를 모두 입력해 주세요.');return
        if self.title.currentText()!='사업보고서':self.notice.setText('연동 시험 XML은 사업보고서 형식만 지원해요. 분기·반기 보고서의 전기 동기 정보는 아직 지원하지 않아요.');return
        if re.fullmatch('[1-9][0-9]*',values['ordinalYear']) is None:self.notice.setText('기수는 1 이상의 정수로 입력해 주세요.');return
        periods={key:{boundary:field.text().strip() for boundary,field in fields.items()} for key,fields in self.periods.items()}
        if any(not value for period in periods.values() for value in period.values()):self.notice.setText('공식 불러오기에 필요한 전기·전전기 시작일과 종료일 네 날짜를 모두 입력해 주세요.');return
        try:
            for key,title in (('priorPeriod','전기'),('secondPriorPeriod','전전기')):
                period=periods[key]
                for value in period.values():
                    try:valid=date.fromisoformat(value).isoformat()==value
                    except (ValueError,TypeError):valid=False
                    if not valid:raise ValueError(title+' 날짜를 실제 달력 날짜 YYYY-MM-DD로 입력해 주세요.')
                if period['start']>period['end']:raise ValueError(title+' 시작일은 종료일보다 늦을 수 없어요.')
            current_start=self.report.get('reporting',{}).get('periodStart','')
            try:valid_start=date.fromisoformat(current_start).isoformat()==current_start
            except (ValueError,TypeError):valid_start=False
            if not valid_start:raise ValueError('당기 시작일을 공시 입력에서 확인해 주세요.')
            if periods['priorPeriod']['end']>=current_start:raise ValueError('전기 종료일은 당기 시작일보다 앞서야 해요.')
            if periods['secondPriorPeriod']['end']>=periods['priorPeriod']['start']:raise ValueError('전전기 종료일은 전기 시작일보다 앞서야 해요.')
        except ValueError as exc:self.notice.setText(str(exc));return
        values.update(approved=True,documentTitle=self.title.currentText(),documentTitleEn=self.titles[self.title.currentText()],
            consolidation=self.report.get('reporting',{}).get('consolidation'),formCodes={key:field.text().strip() for key,field in self.forms.items()},**periods)
        values['extensionPrefix']='entity'+values['centralIndexKey']
        values['extensionNamespace']='http://dart.fss.or.kr/taxonomy/'+str(self.report.get('reporting',{}).get('periodEnd',''))+'/'+values['extensionPrefix']
        self.value=values;self.accept()
