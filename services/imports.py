import csv
import io
import re
from dataclasses import asdict
from datetime import date
from decimal import InvalidOperation
from models import COLUMNS, D, TYPES, Transaction, OpeningPosition

TOLERANCE = D('0.01')

def number(value):
    result = D(str(value).strip())
    if not result.is_finite() or abs(result) > D('1e15'):
        raise ValueError('Numeric value must be finite and within 1e15.')
    return result

def symbol(value):
    value = value.strip().upper()
    if value and (not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', value) or re.fullmatch(r'[A-Z]+[0-9]{6}[CP][0-9]+', value)):
        raise ValueError('Unsupported symbol. Use stock/ETF ticker symbols; options are unsupported.')
    return value

def parse_row(row):
    r = {k: str(row.get(k, '')).strip() for k in COLUMNS}
    for k in ('transaction_id', 'account', 'source'):
        if not r[k] or len(r[k]) > 120:
            raise ValueError(f'{k} is required (maximum 120 characters).')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', r['date']):
        raise ValueError('Date must use YYYY-MM-DD.')
    day = date.fromisoformat(r['date'])
    kind = r['transaction_type'].upper()
    if kind not in TYPES:
        raise ValueError('Unsupported activity: options, shorts, transfers, splits and corporate actions require reconciliation. Supported: ' + ', '.join(TYPES))
    ticker = symbol(r['symbol'])
    if kind in ('BUY', 'SELL', 'DIVIDEND') and not ticker:
        raise ValueError('Symbol is required for trades and dividends.')
    q, p, f, a = (number(r[k]) for k in ('quantity', 'price', 'fees', 'amount'))
    if q < 0 or p < 0 or f < 0:
        raise ValueError('Quantity, price and fees must be nonnegative; shorts are unsupported.')
    if kind in ('BUY', 'SELL'):
        if q <= 0:
            raise ValueError('Trades require positive quantity.')
        expected = -(q * p + f) if kind == 'BUY' else q * p - f
        if abs(a - expected) > TOLERANCE:
            raise ValueError(f'Amount inconsistent with quantity, price and fees (tolerance $0.01); expected {expected}.')
    else:
        if q or p or f:
            raise ValueError('Cash-only activity requires quantity, price and fees = 0. Use a separate FEE row.')
        if kind in ('DIVIDEND', 'DEPOSIT') and a <= 0:
            raise ValueError('Dividend/deposit amount must be positive.')
        if kind in ('WITHDRAWAL', 'FEE') and a >= 0:
            raise ValueError('Withdrawal/fee amount must be negative.')
    if r['currency'].upper() != 'USD':
        raise ValueError('Only USD is supported; no currency conversion is performed.')
    return Transaction(r['transaction_id'], day, r['account'], r['source'], ticker, kind, q, p, f, a)

def read_csv(data, limit_mb=5):
    if len(data) > limit_mb * 1024 * 1024:
        raise ValueError(f'File exceeds {limit_mb} MB limit.')
    try:
        reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')), strict=True)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('CSV requires unique column headers.')
        rows = list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError('CSV rows must have the same number of fields as the header.')
        return reader.fieldnames, rows
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError('Upload a valid UTF-8 CSV file.') from exc

def validate(rows, mapping=None):
    valid, errors = [], []
    for i, row in enumerate(rows, 2):
        try:
            mapped = {k: row.get((mapping or {}).get(k, k), '') for k in COLUMNS}
            valid.append(parse_row(mapped))
        except (ValueError, InvalidOperation) as exc:
            errors.append({'row': i, 'error': str(exc) or 'Invalid numeric value'})
    return valid, errors

def merge(existing, incoming):
    result, duplicates, conflicts = list(existing), 0, []
    known = {t.key: t for t in existing}
    for t in incoming:
        if t.key in known:
            if known[t.key] == t:
                duplicates += 1
            else:
                conflicts.append(f'Conflicting duplicate ID {t.transaction_id} in {t.account}/{t.source}; existing row retained.')
        else:
            known[t.key] = t
            result.append(t)
    return result, duplicates, conflicts

def export_csv(transactions):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    for t in transactions:
        r = asdict(t)
        for k, value in r.items():
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                r[k] = "'" + value
        writer.writerow(r)
    return out.getvalue()

def opening_csv(data):
    _, rows = read_csv(data)
    positions, errors = [], []
    seen = set()
    for i, r in enumerate(rows, 2):
        try:
            account, ticker = r['account'].strip(), symbol(r['symbol'])
            q, basis = number(r['quantity']), number(r['total_cost_basis'])
            day = r['as_of_date']
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
                raise ValueError('as_of_date must use YYYY-MM-DD.')
            if not account or not ticker or q <= 0 or basis < 0 or r['currency'] != 'USD':
                raise ValueError('Opening positions require account, stock symbol, positive quantity, nonnegative known basis and USD.')
            if (account, ticker) in seen:
                raise ValueError('Duplicate opening position.')
            seen.add((account, ticker))
            positions.append(OpeningPosition(account, ticker, q, basis, date.fromisoformat(day)))
        except (ValueError, KeyError, InvalidOperation) as exc:
            errors.append({'row': i, 'error': str(exc)})
    return positions, errors
