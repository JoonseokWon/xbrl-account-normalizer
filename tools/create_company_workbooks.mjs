// Run with the bundled @oai/artifact-tool; no repo dependency installation.
import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const folder=path.resolve(process.argv[2]);
const payload=JSON.parse(await fs.readFile(path.join(folder,'cases.json'),'utf8'));
for(const company of payload.companies){
  const wb=Workbook.create();
  const sheet=wb.worksheets.add('원장');sheet.showGridLines=false;
  const rows=[payload.headers,...company.rows];
  sheet.getRange(`A1:N${rows.length}`).values=rows;
  sheet.getRange(`A1:N${rows.length}`).format.font={name:'Malgun Gothic',size:11};
  sheet.getRange(`A1:N${rows.length}`).format.rowHeight=24;
  sheet.getRange('A1:N1').format={fill:'#25476A',font:{name:'Malgun Gothic',size:11,color:'#FFFFFF',bold:true}};
  sheet.getRange(`A1:F${rows.length}`).setNumberFormat('@');
  sheet.getRange(`G2:H${rows.length}`).setNumberFormat('#,##0;(#,##0);"-"');
  for(const [range,width] of [['A:A',24],['B:B',14],['C:E',14],['F:F',37],['G:H',15],['I:I',65],['J:J',22],['K:L',25],['M:N',16]]){
    const [first,last]=range.split(':');
    sheet.getRange(`${first}1:${last}${rows.length}`).format.columnWidth=width;
  }
  sheet.freezePanes.freezeRows(1);
  wb.recalculate();
  console.log((await wb.inspect({kind:'region',sheetId:'원장',range:'E1:H3',maxChars:500,tableMaxRows:3,tableMaxCols:4})).ndjson);
  await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(folder,`${company.title}_원장.xlsx`));
  const image=await wb.render({sheetName:'원장',range:'A1:H10',scale:1.5,format:'png'});
  await fs.writeFile(path.join(folder,`${company.company}-preview.png`),new Uint8Array(await image.arrayBuffer()));
  console.log(JSON.stringify({company:company.company,rows:company.rows.length,accounts:company.accounts.length}));
}
