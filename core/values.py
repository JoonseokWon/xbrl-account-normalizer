from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from .errors import InputError
from .constants import UNITS

def identifier(value, label):
    # Numeric account cells cannot preserve source leading zeros reliably.
    if not isinstance(value, str) or not value.strip():
        raise InputError(f'{label}: 텍스트 값이 필요합니다. 코드의 앞자리 0을 보존하세요.')
    if len(value) > 2000:
        raise InputError(f'{label}: 텍스트 길이 초과')
    return value.strip()

def day(value):
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise InputError('일자는 YYYY-MM-DD 또는 Excel 날짜 셀이어야 합니다.') from exc

def money(value, unit='원', signed=True):
    if unit not in UNITS or isinstance(value, bool) or value is None:
        raise InputError('금액·단위 누락 또는 미지원 단위')
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', value):
            raise InputError('금액 형식 오류')
        value = value.replace(',', '')
    try:
        number = Decimal(str(value)) * UNITS[unit]
    except InvalidOperation as exc:
        raise InputError('금액 형식 오류') from exc
    if not number.is_finite() or number != number.to_integral_value() or abs(number) > 10**13 or (not signed and number < 0):
        raise InputError('금액은 원 환산 후 정수, 절댓값 10조원 이하가 필요합니다. 음수 차대는 별도 규칙이 필요합니다.')
    return int(number)
