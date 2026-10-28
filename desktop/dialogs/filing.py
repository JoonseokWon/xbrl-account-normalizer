"""Explicit company/fact review for financial-reporting XBRL, separate from GL."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from PySide6.QtCore import QSignalBlocker,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,
    QLineEdit,QComboBox,QPlainTextEdit,QTabWidget,QFileDialog,QScrollArea)

from desktop.components.buttons import button
from desktop.components.text import label
from desktop.components.table import DataTable
from desktop.controllers.jobs import Jobs
from desktop.components.confirmation import confirm
from application.paths import default_outputs


def empty_report():
    return {'schema':'account-normalizer-filing/1','entity':{'name':'','identifier':'','scheme':''},
            'reporting':{'periodStart':'','periodEnd':'','consolidation':'별도','comparativePeriods':[]},'facts':[]}


def parse_comparative_periods(text):
    result=[]
    for pair in text.strip().split(';'):
        if not pair.strip():continue
        parts=pair.strip().split('~')
        if len(parts)!=2:raise ValueError('비교기간은 시작일~종료일을 세미콜론(;)으로 구분해 주세요.')
        start,end=(part.strip() for part in parts)
        if date.fromisoformat(start).isoformat()!=start or date.fromisoformat(end).isoformat()!=end or start>end:
            raise ValueError('비교기간의 시작일·종료일을 YYYY-MM-DD로 확인해 주세요.')
        result.append({'periodStart':start,'periodEnd':end})
    if len(result)>3:raise ValueError('비교기간은 최대 3개까지 입력해 주세요.')
    if len({(r['periodStart'],r['periodEnd']) for r in result})!=len(result):raise ValueError('비교기간이 중복됐어요.')
    return result


def revoke_approvals(report):
    for fact in report.get('facts',[]):fact['approved']=False


class FilingDialog(QDialog):
    def __init__(self,session=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle('IFRS/DART 공시 XML');self.resize(1280,900)
        self.session=session;self.report=empty_report();self.catalog=None;self.jobs=Jobs();self.loading=False
        self.last_export=None;self.work_path=None;self.active_row=-1;self.editor_dirty=False;self.changing=False;self.dirty=False
        root=QVBoxLayout(self)
        root.addWidget(label('확정 재무제표를 공식 공시 개념에 연결해요.','CardTitle',True))
        root.addWidget(label('공시 재무제표용 입력과 XBRL GL 원장은 별도예요. 택사노미·연결/별도·기간을 확인한 뒤 항목별로 승인해 주세요.','Muted',True))
        self.actions=QWidget();actions=QGridLayout(self.actions);actions.setContentsMargins(0,0,0,0)
        definitions=[('공식 택사노미 선택',self.choose_taxonomy),('공시 엑셀·CSV·JSON 열기',self.choose_input),
                     ('공시 엑셀 양식 만들기',self.create_template),('열린 업무의 BS 가져오기',self.use_session),
                     ('공시 업무 열기',self.open_work),('공시 업무 저장',self.save_work),('DART 공식 엑셀 참조 선택',self.choose_dart_reference),
                     ('설치된 DART 스키마 선택',self.choose_installed_taxonomy),('공식 작성기 연동',self.official_writer)]
        self.action_buttons=[]
        for index,(title,callback) in enumerate(definitions):
            action=button(title);action.clicked.connect(callback);actions.addWidget(action,index//3,index%3);self.action_buttons.append(action)
        self.from_session_button=self.action_buttons[3];self.from_session_button.setEnabled(bool(session and session.result.get('financial')))
        root.addWidget(self.actions)
        self.notice=label('공식 택사노미 진입점(.xsd)과 확정 재무제표 파일을 선택해 주세요.','Muted',True);root.addWidget(self.notice)
        self.tabs=QTabWidget();root.addWidget(self.tabs,1)
        self.build_metadata();self.build_facts()
        root.addWidget(label('이 화면은 공시 XML과 검사 근거를 준비해요. DART 편집기에서의 추가 작성·제출·접수 결과는 별도로 확인해 주세요.','Muted',True))
        footer=QHBoxLayout();self.summary=label('입력 항목 0개 · 승인 0개','Muted',True);footer.addWidget(self.summary,1)
        self.open_folder=button('저장 폴더 열기');self.open_folder.setEnabled(False);self.open_folder.clicked.connect(self.show_folder);footer.addWidget(self.open_folder)
        self.export_button=button('검사 후 공시 XML 저장','primary');self.export_button.clicked.connect(self.export);footer.addWidget(self.export_button)
        self.close_button=button('닫기');self.close_button.clicked.connect(self.reject);footer.addWidget(self.close_button);root.addLayout(footer)
        self.populate_report()

    def build_metadata(self):
        pane=QWidget();form=QFormLayout(pane);form.setSpacing(15)
        self.entity_name=QLineEdit();self.entity_id=QLineEdit();self.entity_scheme=QLineEdit()
        self.entity_scheme.setPlaceholderText('식별자 체계를 나타내는 URI')
        self.period_start=QLineEdit();self.period_end=QLineEdit()
        self.period_start.setPlaceholderText('YYYY-MM-DD');self.period_end.setPlaceholderText('YYYY-MM-DD')
        self.consolidation=QComboBox();self.consolidation.addItems(['별도','연결'])
        self.comparatives=QLineEdit();self.comparatives.setPlaceholderText('2025-01-01~2025-12-31;2024-01-01~2024-12-31')
        self.taxonomy_path=QLineEdit();self.taxonomy_path.setReadOnly(True)
        self.taxonomy_summary=label('택사노미를 아직 선택하지 않았어요.','Muted',True)
        self.reviewer=QLineEdit();self.reviewer.setPlaceholderText('공시 항목을 확인한 사람의 이름')
        for title,field in [('회사명',self.entity_name),('기업 식별자',self.entity_id),('식별자 체계 URI',self.entity_scheme),
                            ('당기 시작일',self.period_start),('당기 종료일',self.period_end),('연결/별도',self.consolidation),
                            ('비교기간 (최대 3개)',self.comparatives),('택사노미 진입점',self.taxonomy_path),('',self.taxonomy_summary),('확인자',self.reviewer)]:form.addRow(title,field)
        form.addRow('',label('비교금액을 입력했다면 해당 비교기간도 명시해 주세요. 원장 거래 합계에서 PL·현금흐름·기말잔액을 추정하지 않아요.','Muted',True))
        for field in (self.entity_name,self.entity_id,self.entity_scheme,self.period_start,self.period_end,self.comparatives):field.textEdited.connect(self.metadata_changed)
        self.consolidation.currentIndexChanged.connect(self.metadata_changed)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(pane);self.tabs.addTab(scroll,'회사·공시 범위')

    def build_facts(self):
        pane=QWidget();body=QVBoxLayout(pane)
        self.fact_table=DataTable(['표','원본 항목','공식 개념','값','기간','승인']);self.fact_table.setMinimumHeight(220);body.addWidget(self.fact_table,1)
        self.fact_table.selectionModel().currentRowChanged.connect(self.select_fact)
        editor=QWidget();grid=QGridLayout(editor);grid.setContentsMargins(0,0,0,0)
        self.original=label('검토할 항목을 선택해 주세요.','Muted',True);grid.addWidget(self.original,0,0,1,2)
        left=QWidget();left_form=QFormLayout(left);right=QWidget();right_form=QFormLayout(right)
        self.search=QLineEdit();self.search.setPlaceholderText('공식 개념의 한국어·영문 이름 또는 코드 검색')
        self.search.textChanged.connect(self.search_concepts)
        self.role_filter=QComboBox();self.role_filter.addItem('전체 공시 개념','');self.role_filter.setMaxVisibleItems(12)
        self.role_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.role_filter.setMinimumContentsLength(20)
        self.role_filter.currentIndexChanged.connect(lambda:self.search_concepts(self.search.text()))
        self.concept=QComboBox();self.concept.setMinimumContentsLength(20)
        self.concept.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.concept_info=label('선택한 개념의 기간형식을 확인해 주세요.','Muted',True)
        self.statement=QComboBox();self.statement.addItems(['BS','PL','CF','CE','NOTE'])
        self.fact_value=QLineEdit();self.fact_value.setMaxLength(100_000)
        self.period_kind=QComboBox();self.period_kind.addItems(['instant','duration'])
        self.fact_start=QLineEdit();self.fact_end=QLineEdit();self.fact_instant=QLineEdit()
        for edit in (self.fact_start,self.fact_end,self.fact_instant):edit.setPlaceholderText('YYYY-MM-DD')
        self.fact_unit=QComboBox();self.fact_unit.addItems(['KRW','shares','KRW/shares','pure',''])
        self.decimals=QComboBox();self.decimals.setEditable(True);self.decimals.addItems(['0','-3','-6','INF'])
        self.dimensions=QPlainTextEdit();self.dimensions.setMaximumHeight(72);self.dimensions.setPlaceholderText('{"택사노미:축": "택사노미:멤버"} 또는 {}')
        for title,field in [('개념 검색',self.search),('DART 서식별 검색',self.role_filter),('공식 개념',self.concept),('',self.concept_info),('재무제표',self.statement),('공시 표시값',self.fact_value)]:left_form.addRow(title,field)
        for title,field in [('기간형식',self.period_kind),('기준일 (instant)',self.fact_instant),('시작일 (duration)',self.fact_start),('종료일 (duration)',self.fact_end),('단위',self.fact_unit),('정확도 decimals',self.decimals),('차원 연결 JSON',self.dimensions)]:right_form.addRow(title,field)
        grid.addWidget(left,1,0);grid.addWidget(right,1,1)
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1)
        grid.addWidget(label('instant는 특정 기준일, duration은 시작일~종료일이에요. decimals=-3은 천원 단위 정확도이며 표시값을 다시 1,000배 하지 않아요. 차원은 축·멤버의 공식 QName으로 입력해요.','Muted',True),2,0,1,2)
        line=QHBoxLayout();self.apply=button('변경 적용');self.apply.clicked.connect(lambda:self.apply_fact(False));line.addWidget(self.apply)
        self.approve=button('선택 항목 승인','primary');self.approve.clicked.connect(lambda:self.apply_fact(True));line.addWidget(self.approve)
        self.unapprove=button('선택 항목 승인 취소');self.unapprove.clicked.connect(self.unapprove_fact);line.addWidget(self.unapprove)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(editor);body.addWidget(scroll,2)
        body.addLayout(line)
        self.tabs.addTab(pane,'공시 항목 연결·승인');self.editor=editor;self.editor.setEnabled(False)
        for field in (self.fact_value,self.fact_start,self.fact_end,self.fact_instant):field.textEdited.connect(self.editor_changed)
        for field in (self.concept,self.statement,self.period_kind,self.fact_unit,self.decimals):field.currentTextChanged.connect(self.editor_changed)
        self.dimensions.textChanged.connect(self.editor_changed);self.period_kind.currentTextChanged.connect(self.period_controls)
        self.concept.currentIndexChanged.connect(self.describe_concept)

    def set_busy(self,busy,message=''):
        self.loading=busy;self.tabs.setEnabled(not busy);self.actions.setEnabled(not busy);self.close_button.setEnabled(not busy)
        self.export_button.setEnabled(not busy);self.open_folder.setEnabled(not busy and bool(self.last_export))
        if message:self.notice.setText(message)

    def run(self,function,success,message):
        if self.loading:return
        self.set_busy(True,message)
        def done(value):
            self.set_busy(False)
            try:success(value)
            except Exception as error:self.notice.setText(str(error))
        self.jobs.start(function,done,self.failed)

    def failed(self,message,trace):
        self.set_busy(False);self.notice.setText(message or '공시 자료를 처리하지 못했어요. 입력과 연결을 확인해 주세요.')

    def update_summary(self):
        facts=self.report.get('facts',[]);approved=sum(bool(f.get('approved')) for f in facts)
        self.summary.setText(f'입력 항목 {len(facts):,}개 · 승인 {approved:,}개 · 미확정 {len(facts)-approved:,}개')

    def metadata_changed(self,*args):
        if self.changing:return
        revoke_approvals(self.report);self.dirty=True;self.refresh_table();self.notice.setText('공시 범위가 바뀌어 항목 승인을 취소했어요. 금액·기간·개념을 다시 확인해 주세요.')

    def editor_changed(self,*args):
        if self.changing or self.active_row<0:return
        self.editor_dirty=True;self.dirty=True;self.report['facts'][self.active_row]['approved']=False;self.update_summary()
        self.refresh_table()

    def metadata(self):
        return {'name':self.entity_name.text().strip(),'identifier':self.entity_id.text().strip(),'scheme':self.entity_scheme.text().strip()}, {
            'periodStart':self.period_start.text().strip(),'periodEnd':self.period_end.text().strip(),'consolidation':self.consolidation.currentText(),
            'comparativePeriods':parse_comparative_periods(self.comparatives.text())}

    def commit(self):
        if self.editor_dirty and not self.apply_fact(False):return False
        try:entity,reporting=self.metadata()
        except ValueError as error:self.notice.setText(str(error));return False
        self.report['entity']=entity;self.report['reporting']=reporting;return True

    def populate_report(self):
        self.changing=True
        entity=self.report.get('entity',{});meta=self.report.get('reporting',{})
        for field,value in ((self.entity_name,entity.get('name','')),(self.entity_id,entity.get('identifier','')),(self.entity_scheme,entity.get('scheme','')),
                            (self.period_start,meta.get('periodStart','')),(self.period_end,meta.get('periodEnd',''))):field.setText(str(value or ''))
        self.consolidation.setCurrentText(meta.get('consolidation','별도'))
        self.comparatives.setText(';'.join(str(p.get('periodStart',''))+'~'+str(p.get('periodEnd','')) for p in meta.get('comparativePeriods',[])))
        self.active_row=-1;self.editor_dirty=False;self.changing=False;self.refresh_table()
        if self.report.get('facts'):self.fact_table.selectRow(0)
        else:self.editor.setEnabled(False)

    def refresh_table(self,select=True):
        selected=self.active_row
        blocker=QSignalBlocker(self.fact_table.selectionModel())
        self.fact_table.set_rows([[f.get('statement'),f.get('originalName') or f.get('originalCode'),f.get('concept'),f.get('value'),
            f.get('period',{}).get('instant') or f.get('period',{}).get('start','')+' ~ '+f.get('period',{}).get('end',''),
            '확인' if f.get('approved') else '미확정'] for f in self.report.get('facts',[])])
        if select and 0<=selected<len(self.report.get('facts',[])):self.fact_table.selectRow(selected)
        del blocker;self.update_summary()

    def select_fact(self,current,previous):
        if self.changing:return
        row=current.row()
        if self.editor_dirty and not self.apply_fact(False):
            blocker=QSignalBlocker(self.fact_table.selectionModel());self.fact_table.selectRow(self.active_row);del blocker;return
        if not current.isValid() or not 0<=row<len(self.report.get('facts',[])):return
        self.active_row=row;fact=self.report['facts'][row];self.changing=True;self.editor.setEnabled(True)
        self.original.setText(f"{fact.get('originalCode','')} {fact.get('originalName','')}\n원본: {fact.get('source','')}")
        self.search.setText('');self.search_concepts('');self.set_concept(fact.get('concept',''))
        self.statement.setCurrentText(fact.get('statement','BS'));self.fact_value.setText(str(fact.get('value','')))
        period=fact.get('period',{});self.period_kind.setCurrentText(period.get('kind','instant'))
        self.fact_instant.setText(period.get('instant',''));self.fact_start.setText(period.get('start',''));self.fact_end.setText(period.get('end',''))
        self.fact_unit.setCurrentText(fact.get('unit','KRW'));self.decimals.setCurrentText(str(fact.get('decimals','0')))
        self.dimensions.setPlainText(json.dumps(fact.get('dimensions',{}),ensure_ascii=False))
        if fact.get('reviewer') and not self.reviewer.text():self.reviewer.setText(fact['reviewer'])
        self.editor_dirty=False;self.changing=False;self.period_controls();self.describe_concept()
        blocker=QSignalBlocker(self.fact_table.selectionModel());self.fact_table.selectRow(row);del blocker

    def search_concepts(self,text):
        if self.catalog is None:return
        current=self.concept.currentData();items=self.catalog.get('concepts',{});needle=text.strip().casefold()
        suggestions=self.report['facts'][self.active_row].get('suggestions',[]) if 0<=self.active_row<len(self.report.get('facts',[])) else []
        role=self.role_filter.currentData();allowed=set(self.catalog.get('roles',{}).get(role,{}).get('concepts',[])) if role else None
        matches=[(q,c) for q,c in items.items() if not c.get('abstract') and c.get('kind')!='unsupported' and (allowed is None or q in allowed) and (not needle or needle in (q+' '+str(c.get('label',''))).casefold())]
        matches.sort(key=lambda pair:(pair[0] not in suggestions,pair[0]));matches=matches[:200]
        blocker=QSignalBlocker(self.concept);self.concept.clear();self.concept.addItem('공식 개념을 선택해 주세요','')
        for q,c in matches:self.concept.addItem(str(c.get('label') or q)+'  ['+q+']',q)
        if current and current in items and current not in {q for q,_ in matches}:self.concept.addItem(str(items[current].get('label') or current)+'  ['+current+']',current)
        index=self.concept.findData(current);self.concept.setCurrentIndex(index if index>=0 else 0);del blocker
        self.describe_concept()

    def set_concept(self,qname):
        index=self.concept.findData(qname)
        if index<0 and qname:
            concept=(self.catalog or {}).get('concepts',{}).get(qname,{})
            self.concept.addItem(str(concept.get('label') or qname)+'  ['+qname+']',qname);index=self.concept.count()-1
        self.concept.setCurrentIndex(max(0,index))

    def describe_concept(self,*args):
        concept=(self.catalog or {}).get('concepts',{}).get(self.concept.currentData(),{})
        self.concept_info.setText('기간형식: '+str(concept.get('periodType','—'))+' · 자료형: '+str(concept.get('type','—')) if concept else '검색 결과는 최대 200개예요. 공식 개념을 선택해 주세요.')

    def period_controls(self,*args):
        instant=self.period_kind.currentText()=='instant'
        self.fact_instant.setEnabled(instant);self.fact_start.setEnabled(not instant);self.fact_end.setEnabled(not instant)

    def apply_fact(self,approve=False):
        if self.active_row<0:return False
        try:
            dimensions=json.loads(self.dimensions.toPlainText() or '{}')
            if not isinstance(dimensions,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in dimensions.items()):raise ValueError('차원 연결은 공식 축 QName과 멤버 QName의 JSON 객체로 입력해 주세요.')
            qname=self.concept.currentData() or '';concept=(self.catalog or {}).get('concepts',{}).get(qname)
            if approve and (not concept or concept.get('abstract')):raise ValueError('공식 택사노미에서 사용할 개념을 선택해 주세요.')
            if approve and not self.reviewer.text().strip():raise ValueError('회사·공시 범위 탭에 확인자 이름을 입력해 주세요.')
            kind=self.period_kind.currentText();period={'kind':kind}
            if kind=='instant':period['instant']=self.fact_instant.text().strip()
            else:period.update(start=self.fact_start.text().strip(),end=self.fact_end.text().strip())
            if approve:
                for value in (period.get('instant'),period.get('start'),period.get('end')):
                    if value is not None and date.fromisoformat(value).isoformat()!=value:raise ValueError('일자는 YYYY-MM-DD로 입력해 주세요.')
                if concept.get('periodType') and concept['periodType']!=kind:raise ValueError('선택한 공식 개념의 instant/duration과 기간형식이 달라요.')
                if kind=='duration' and period['start']>period['end']:raise ValueError('시작일이 종료일보다 늦어요.')
            fact=self.report['facts'][self.active_row]
            fact.update(concept=qname,statement=self.statement.currentText(),value=self.fact_value.text(),period=period,unit=self.fact_unit.currentText(),
                decimals=self.decimals.currentText(),dimensions=dimensions,reviewer=self.reviewer.text().strip() if approve else fact.get('reviewer',''),approved=bool(approve))
            if approve:
                self.report['taxonomyFingerprint']=self.catalog.get('fingerprint','')
                self.report['taxonomyEntryPoint']=self.catalog.get('entryPoint','')
            self.editor_dirty=False;self.dirty=True;self.refresh_table();self.notice.setText('선택 항목을 승인했어요.' if approve else '변경을 반영했어요. 항목 승인을 다시 확인해 주세요.');return True
        except (ValueError,TypeError) as error:self.notice.setText(str(error));return False

    def unapprove_fact(self):
        if self.active_row>=0:self.report['facts'][self.active_row]['approved']=False;self.dirty=True;self.refresh_table();self.notice.setText('선택 항목의 승인을 취소했어요.')

    def can_replace(self):
        return not self.dirty or confirm(self,'현재 공시 업무를 바꿀까요?','저장하지 않은 공시 항목 연결이 있어요. 공시 업무 저장으로 이어서 작업할 수 있어요.','저장하지 않고 변경')

    def choose_taxonomy(self):
        if not self.commit():return
        path,_=QFileDialog.getOpenFileName(self,'공식 IFRS/DART 택사노미 진입점 선택',str(Path.home()/'Downloads'),'XBRL 진입점 (*.xsd)')
        if not path:return
        from application.filing import load_taxonomy
        self.run(lambda:load_taxonomy(path),self.taxonomy_ready,'택사노미 개념과 기간형식을 읽고 있어요. 공식 배포 폴더를 함께 보관해 주세요.')

    def taxonomy_ready(self,catalog):
        changed=self.report.get('taxonomyFingerprint')!=catalog.get('fingerprint');self.catalog=catalog
        if changed:revoke_approvals(self.report);self.dirty=True
        self.report['taxonomyFingerprint']=catalog.get('fingerprint','');self.report['taxonomyEntryPoint']=catalog.get('entryPoint','')
        self.taxonomy_path.setText(str(catalog.get('entryPoint','')))
        self.taxonomy_summary.setText(f"개념 {len(catalog.get('concepts',{})):,}개 · {str(catalog.get('fingerprint',''))[:16]}")
        blocker=QSignalBlocker(self.role_filter);self.role_filter.clear();self.role_filter.addItem('전체 공시 개념','')
        for uri,role in catalog.get('roles',{}).items():
            self.role_filter.addItem(str(role.get('definition') or role.get('label') or uri),uri)
        del blocker
        reference=catalog.get('mode')=='dart-reference'
        self.export_button.setText('검사 후 DART 대사표 저장' if reference else '검사 후 공시 XML 저장')
        if reference:self.taxonomy_summary.setText('DART 공식 엑셀 개념 참조 · XSD가 아니므로 XML을 생성하지 않아요. 개념 연결·대사표를 저장해 공식 작성기에서 확인해 주세요.')
        from application.filing import suggest_concepts
        self.run(lambda:suggest_concepts(deepcopy(self.report),catalog),lambda value:self.report_ready(value,'공식 개념 후보를 준비했어요. 후보는 직접 확인한 뒤 승인해 주세요.'),'공시 항목의 공식 개념 후보를 찾고 있어요.')

    def choose_dart_reference(self):
        if not self.commit():return
        path,_=QFileDialog.getOpenFileName(self,'금융감독원 DART 택사노미 공식 엑셀 선택',str(Path.home()/'Downloads'),'DART 개념 참조 (*.xlsx)')
        if not path:return
        from application.filing import load_dart_reference
        self.run(lambda:load_dart_reference(path),self.taxonomy_ready,'DART 공식 엑셀의 개념·표시명·업종·연결/별도 서식을 읽고 있어요. XML 스키마 검사와는 별도예요.')

    def choose_installed_taxonomy(self):
        if not self.commit():return
        from application.official_writer import load_installed_taxonomy
        self.run(load_installed_taxonomy,self.taxonomy_ready,'공식 작성기에 설치된 DART 스키마의 개념·자료형을 읽고 있어요.')

    def official_writer(self):
        if not self.commit():return
        from desktop.dialogs.official_writer import OfficialWriterDialog
        dialog=OfficialWriterDialog(deepcopy(self.report),self.catalog,self);dialog.exec()
        if dialog.last_export:self.notice.setText('작성기 연동 작업을 보관했어요. 작업 기록에서 생성·검사 상태를 확인해 주세요.')

    def choose_input(self):
        if not self.can_replace():return
        path,_=QFileDialog.getOpenFileName(self,'확정 재무제표 파일 선택',str(Path.home()/'Documents'),'공시 자료 (*.xlsx *.csv *.json)')
        if not path:return
        from application.filing import read_filing_input
        self.run(lambda:read_filing_input(path),lambda value:self.input_ready(value,Path(path).name),'확정 재무제표의 공시 항목을 읽고 있어요.')

    def use_session(self):
        if not self.session or not self.can_replace():return
        from application.filing import from_session
        self.run(lambda:from_session(self.session),lambda value:self.input_ready(value,'열린 업무의 BS'),'열린 업무의 BS 표시값을 가져오고 있어요. 원장은 집계하지 않아요.')

    def input_ready(self,value,name):
        self.report=value;self.work_path=None;self.dirty=True;revoke_approvals(self.report)
        if self.catalog:
            self.report['taxonomyFingerprint']=self.catalog.get('fingerprint','');self.report['taxonomyEntryPoint']=self.catalog.get('entryPoint','')
            from application.filing import suggest_concepts
            self.run(lambda:suggest_concepts(deepcopy(value),self.catalog),lambda v:self.report_ready(v,name+' 항목을 불러왔어요. 공식 개념을 확인해 주세요.'),'공시 개념 후보를 찾고 있어요.')
        else:self.report_ready(value,name+' 항목을 불러왔어요. 공식 택사노미를 선택해 주세요.')

    def report_ready(self,value,message):
        self.report=value;self.populate_report();self.notice.setText(message)

    def create_template(self):
        path,_=QFileDialog.getSaveFileName(self,'공시 엑셀 양식 만들기',str(default_outputs()/'공시재무제표_입력양식.xlsx'),'Excel (*.xlsx)')
        if not path:return
        if not path.lower().endswith('.xlsx'):path+='.xlsx'
        from application.filing import create_filing_template
        self.run(lambda:create_filing_template(path),lambda value:self.notice.setText('공시 입력 양식을 만들었어요. 확정 재무제표를 입력한 뒤 파일을 열어 주세요. '+Path(value).name),'공시 입력 양식을 만들고 있어요.')

    def open_work(self):
        if not self.can_replace():return
        path,_=QFileDialog.getOpenFileName(self,'공시 업무 열기',str(default_outputs()),'공시 업무 (*.acfiling)')
        if not path:return
        from application.filing import load_filing_work
        def ready(value):
            matched=bool(self.catalog and value.get('taxonomyFingerprint')==self.catalog.get('fingerprint'))
            if not matched:revoke_approvals(value)
            self.work_path=Path(path);self.dirty=not matched
            self.report_ready(value,'공시 업무를 열었어요. 택사노미가 일치하지 않아 항목을 다시 승인해 주세요.' if not matched else '공시 업무와 같은 택사노미를 확인했어요. 저장된 승인을 유지했어요.')
        self.run(lambda:load_filing_work(path),ready,'저장한 공시 업무를 읽고 있어요.')

    def save_work(self):
        if not self.commit():return
        path,_=QFileDialog.getSaveFileName(self,'공시 업무 저장',str(self.work_path or default_outputs()/'새공시업무.acfiling'),'공시 업무 (*.acfiling)')
        if not path:return
        if not path.lower().endswith('.acfiling'):path+='.acfiling'
        from application.filing import save_filing_work
        value=deepcopy(self.report)
        def ready(result):self.work_path=Path(path);self.dirty=False;self.notice.setText('미확정 항목을 포함해 공시 업무를 저장했어요. '+Path(path).name)
        self.run(lambda:save_filing_work(value,path),ready,'공시 입력과 검토 상태를 업무 파일로 저장하고 있어요.')

    def export(self):
        if not self.commit():return
        if not self.catalog:self.notice.setText('공식 택사노미 진입점을 먼저 선택해 주세요.');return
        facts=self.report.get('facts',[])
        if not facts or any(not f.get('approved') for f in facts):self.notice.setText('모든 공시 항목의 개념·금액·기간을 확인하고 승인해 주세요.');return
        folder=QFileDialog.getExistingDirectory(self,'공시 XML 패키지를 저장할 위치 선택',str(default_outputs().parent))
        if not folder:return
        from application.filing import export_filing,export_dart_handoff
        value=deepcopy(self.report);catalog=self.catalog
        reference=catalog.get('mode')=='dart-reference';exporter=export_dart_handoff if reference else export_filing
        def ready(path):
            self.last_export=Path(path);self.open_folder.setEnabled(True);self.notice.setText(('DART 입력·대사표와 검사 범위를 저장했어요. 공식 작성기에서 제출용 파일을 생성해 주세요. ' if reference else '공시 XML과 검사 기록을 새 폴더에 저장했어요. ')+Path(path).name)
        self.run(lambda:exporter(value,catalog,folder),ready,'DART 개념 연결·기간·금액을 확인하고 있어요.' if reference else '공시 XML을 만들고 택사노미·기간·차원·금액을 검사하고 있어요.')

    def show_folder(self):
        if self.last_export:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_export)))

    def reject(self):
        if self.loading:return
        if self.dirty and not confirm(self,'공시 준비 화면을 닫을까요?','저장하지 않은 연결이 있어요. 공시 업무 저장으로 다음에 이어서 확인할 수 있어요.','저장하지 않고 닫기'):return
        super().reject()

    def closeEvent(self,event):
        if self.loading:event.ignore()
        elif self.dirty:
            event.ignore();self.reject()
        else:super().closeEvent(event)
