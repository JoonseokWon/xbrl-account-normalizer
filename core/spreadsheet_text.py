"""Neutralize formula-like text on first CSV export; preserve original content."""
import re


def csv_text(value, preserve_zeroes=False):
    text = '' if value is None else str(value)
    if (text.lstrip().startswith(('=', '+', '-', '@', '＝', '＋', '－', '＠'))
            or text.startswith(('\t', '\r', '\n'))
            or (preserve_zeroes and re.fullmatch(r'0[0-9]+', text))):
        return "'" + text
    return text
