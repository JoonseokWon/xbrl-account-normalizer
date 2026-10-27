"""Treat saved, unsigned source metadata as untrusted before enabling UI links."""
import re

def source_hashes(source):
    if not isinstance(source,dict):return set()
    sources=source.get('files') if 'files' in source else [source]
    if not isinstance(sources,list) or not 1<=len(sources)<=24:return set()
    hashes=[]
    for item in sources:
        if not isinstance(item,dict):return set()
        value=item.get('sha256')
        if not isinstance(value,str) or re.fullmatch(r'[0-9a-fA-F]{64}',value) is None:return set()
        hashes.append(value.lower())
    return set(hashes) if len(set(hashes))==len(hashes) else set()
