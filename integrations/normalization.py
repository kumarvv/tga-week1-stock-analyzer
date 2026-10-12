from datetime import datetime
from decimal import InvalidOperation
from zoneinfo import ZoneInfo
from services.imports import parse_row


def normalize_transactions(rows, account):
    accepted, flags = [], []
    for row in rows:
        try:
            b = row.get('brokerage', {})
            product = b.get('product', {})
            kind = str(b.get('transactionType') or row.get('transactionType', '')).upper()
            # Never interpret a transfer or description as a deposit/trade.
            if product.get('securityType') not in (None, '', 'EQ'):
                raise ValueError('Unsupported non-equity activity')
            if kind not in ('BUY', 'SELL', 'DIVIDEND', 'DEPOSIT', 'WITHDRAWAL', 'FEE'):
                raise ValueError('Unsupported or ambiguous broker activity: ' + kind)
            if kind in ('BUY', 'SELL', 'DIVIDEND') and product.get('securityType') != 'EQ':
                raise ValueError('Missing verified equity security type')
            raw_date = int(row['transactionDate'])
            day = datetime.fromtimestamp(raw_date / 1000, ZoneInfo('America/New_York')).date()
            accepted.append(parse_row(dict(transaction_id=str(row['transactionId']), date=day.isoformat(), account=account, source='E*TRADE', symbol=product.get('symbol', ''), transaction_type=kind, quantity=b.get('quantity', 0), price=b.get('price', 0), fees=b.get('fee', 0), amount=row['amount'], currency=b.get('settlementCurrency', ''))))
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            flags.append({'transaction_id': str(row.get('transactionId', '?')), 'error': str(exc)})
    return accepted, flags
