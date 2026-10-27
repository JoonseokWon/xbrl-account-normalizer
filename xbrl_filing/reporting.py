"""Offline, escaped reports and a neutral DART data reconciliation table."""
import csv
import html
import json
import re


def _safe_cell(value):
    value=str(value)
    # A CSV is opened in spreadsheets; untrusted account names must remain text.
    if value.startswith(('=','+','-','@','\t','\r','\n')) or re.fullmatch('0[0-9]+',value):return "'"+value
    return value


def write_handoff(path,report):
    with path.open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['회사명','기업식별자','연결구분','표','항목ID','원본코드','원본항목','공식개념','공시값','단위','정확도','기간','차원','원본위치','확인자'])
        for fact in report['facts']:
            period=fact['period'];at=period.get('instant') or period['start']+'~'+period['end']
            cells=[report['entity']['name'],report['entity']['identifier'],report['reporting']['consolidation'],fact['statement'],fact.get('originalId',fact['id']),
                   fact.get('originalCode',''),fact.get('originalName',''),fact['concept'],fact['value'],fact['unit'],fact.get('decimals',''),at,
                   json.dumps(fact['dimensions'],ensure_ascii=False),fact['source'],fact['reviewer']]
            # The value column is a validated decimal/text fact; keep numeric negatives usable.
            writer.writerow([str(c) if i in (8,10) and re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?|INF',str(c)) else _safe_cell(c) for i,c in enumerate(cells)])
    return path


def write_filing_report(path,report,validation):
    esc=lambda x:html.escape(str(x),quote=True)
    rows=''.join('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in [f['statement'],f.get('originalName',''),f['concept'],f['value'],f['unit'],
        json.dumps(f['period'],ensure_ascii=False),f['source'],f['reviewer']])+'</tr>' for f in report['facts'][:500])
    warnings=validation.get('warnings',[])
    warning_html=''.join('<li>'+esc(w.get('message',w) if isinstance(w,dict) else w)+'</li>' for w in warnings)
    result='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>공시 XML 검사 결과</title>
<style>body{font-family:'Malgun Gothic','Noto Sans KR',sans-serif;background:#f4f6fa;color:#182538;margin:0;padding:36px;line-height:1.65}main{max-width:1500px;margin:auto}section{background:white;border:1px solid #e4e9f1;border-radius:20px;padding:24px;margin:18px 0}h1{font-size:28px}h2{font-size:20px}.ok{background:#e6f7ef}.note{background:#fff6de}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #e6eaf0;text-align:left;padding:10px;overflow-wrap:anywhere}th{background:#f3f6fc}.scroll{overflow:auto}a{color:#2463eb}</style><main>
<h1>공시 XML 검사를 통과했어요</h1><section class="ok"><b>'''+esc(report['entity']['name'])+' · '+esc(report['reporting']['consolidation'])+' · '+esc(report['reporting']['periodStart'])+'~'+esc(report['reporting']['periodEnd'])+'''</b><p>공시 항목 '''+str(len(report['facts']))+'개 · '+esc(validation.get('validator','Arelle'))+' '+esc(validation.get('version',''))+'''</p></section>
<section><h2>확인한 내용</h2><p>선택한 로컬 DTS로 XBRL 2.1·개념 자료형·기간·단위·명시적 차원을 검사했습니다. 원본 파일 해시와 항목 승인을 확인했어요.</p><p>계산 검사는 불러온 계산 링크와 제공한 팩트에 한정합니다. 누락된 하위 항목이 있는 계산은 전체 합계가 검증됐다는 뜻이 아니에요. Formula 전체·회사별 공시 완전성·회계 적정성·DART 접수 규칙은 별도입니다.</p><p>택사노미 지문: '''+esc(validation['taxonomyFingerprint'])+'''</p></section>
<section class="note"><h2>DART 제출 전 확인</h2><p>이 결과는 공식 작성기가 만든 DART 접수용 최종 파일이 아닙니다. 금융감독원 공식 XBRL 작성기에서 제출용 파일 생성·검사를 하고 DART 편집기에 삽입해 제출하세요. 함께 저장한 CSV는 입력·대사용이며 자동 불러오기 규격이 아닙니다.</p><p>공식 IFRS/DART 택사노미 원본은 이 결과에 포함하지 않아요. 사용 권한이 있는 배포 폴더를 별도로 보관해 주세요.</p></section>
<section><h2>검사 주의 '''+str(len(warnings))+'''개</h2><ul>'''+warning_html+'''</ul><a href="validation-report.json">검사 상세 JSON</a> · <a href="financial-report.xbrl">XML</a> · <a href="DART_입력대사.csv">DART 입력·대사표</a></section>
<section><h2>원본과 공시 개념 연결</h2><p>처음 500개 항목을 표시합니다. 전체 항목은 facts.json과 CSV에 보관합니다.</p><div class="scroll"><table><thead><tr>'''+''.join('<th>'+s+'</th>' for s in ['표','원본 항목','공식 개념','공시값','단위','기간','원본 위치','확인자'])+'</tr></thead><tbody>'+rows+'</tbody></table></div></section></main></html>'
    with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(result)
    return path
