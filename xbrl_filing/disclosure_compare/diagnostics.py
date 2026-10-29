"""Explain exact numeric differences without weakening comparison outcomes."""
from decimal import Decimal, localcontext


def numeric_diagnostics(source_number, actual_value, scale):
    """Hints only: never flip signs, infer zero, change units or pass a mismatch."""
    with localcontext() as context:
        context.prec = max(250, 2 * (len(source_number) + len(actual_value) + len(str(scale))) + 100)
        raw, actual, multiplier = Decimal(source_number), Decimal(actual_value), Decimal(scale)
        normalized = raw * multiplier
        if normalized == actual:
            return []
        hints = []
        if normalized and actual and normalized == -actual:
            hints.append({'code': 'sign', 'label': '부호 확인',
                          'detail': '절댓값이 같고 부호가 반대예요. 차변·대변 및 손익 표시 기준을 확인해 주세요.'})
        alternatives = [str(value) for value in ('1', '1000', '1000000')
                        if Decimal(value) != multiplier and raw * Decimal(value) == actual]
        if alternatives:
            hints.append({'code': 'scale', 'label': '표시 단위 확인', 'suggestedScales': alternatives,
                          'detail': '다른 표시 배율에서는 값이 같아요. 원·천원·백만원 여부를 원문에서 확인해 주세요.'})
        # This is the source display's decimal place, not XBRL decimals or an
        # allowed regulatory tolerance. A nonzero difference stays a mismatch.
        quantum = Decimal(1).scaleb(raw.as_tuple().exponent) * multiplier
        if abs(normalized - actual) <= abs(quantum) / 2:
            hints.append({'code': 'display-rounding', 'label': '단수 차이 가능성',
                          'detail': '차이가 DSD 마지막 표시 자리의 절반 이내예요. 반올림 기준과 원금액을 확인해 주세요.'})
        return hints
