from collections import defaultdict

def journal_groups(ledger):
    groups=defaultdict(list)
    for row in ledger:groups[(row['company'],row['system'],row['journalId'])].append(row)
    output=[]
    for key,rows in groups.items():
        debit=sum(r['debit'] for r in rows);credit=sum(r['credit'] for r in rows)
        output.append({'key':key,'company':key[0],'journal':key[2],'date':', '.join(sorted({r['postingDate'] for r in rows})),
                       'rows':rows,'debit':debit,'credit':credit,'difference':debit-credit,
                       'debitAccounts':', '.join(dict.fromkeys(r['originalName'] for r in rows if r['debit'])),
                       'creditAccounts':', '.join(dict.fromkeys(r['originalName'] for r in rows if r['credit']))})
    return output
