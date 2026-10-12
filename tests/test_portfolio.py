from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
import pytest
from models import D, Quote, OpeningPosition
from services.imports import read_csv, validate, merge, parse_row, export_csv, opening_csv
from services.calculations import calculate
from integrations.normalization import normalize_transactions

@pytest.fixture
def sample():
    _, rows = read_csv(Path('sample_data/transactions.csv').read_bytes())
    valid, errors = validate(rows)
    assert not errors
    return valid

def trade(id, kind, q, p, fees='0', account='A', day='2025-01-01'):
    q, p, f = map(D, (q, p, fees))
    amount = -(q*p+f) if kind == 'BUY' else q*p-f
    return parse_row(dict(transaction_id=id,date=day,account=account,source='CSV',symbol='AAPL',transaction_type=kind,quantity=q,price=p,fees=f,amount=amount,currency='USD'))

def test_sample_acceptance(sample):
    r = calculate(sample, as_of=date(2025,4,15))
    h = {h['symbol']: h for h in r['holdings']}
    assert h['AAPL']['quantity'] == D('8')
    assert h['MSFT']['quantity'] == D('5')
    assert r['cash'] == D('6099.50')
    assert h['AAPL']['cost_basis'] == D('1440.80')
    assert r['realized'] == D('38.80')
    assert r['dividends'] == D('2.50')
    assert r['contributions'] == D('9500')

def test_multiple_lots_fractional_and_fees():
    tx = [trade('1','BUY','1.5','100','1'), trade('2','BUY','2','200','2'), trade('3','SELL','2','250','3')]
    r = calculate(tx)
    assert r['realized'] == D('245.5')
    assert r['holdings'][0]['quantity'] == D('1.5')
    assert r['holdings'][0]['cost_basis'] == D('301.5')
    assert len(r['sales'][0]['lots']) == 2

def test_account_isolation():
    r = calculate([trade('1','BUY','1','10',account='A'), trade('1','BUY','1','100',account='B'), trade('2','SELL','1','20',account='A')])
    assert r['realized'] == D('10')
    assert r['holdings'][0]['account'] == 'B'
    assert r['holdings'][0]['cost_basis'] == D('100')

def test_period_uses_prior_history(sample):
    r = calculate(sample, as_of=date(2025,4,15), start=date(2025,4,1))
    assert r['realized'] == D('38.80')
    assert r['dividends'] == 0
    assert r['contributions'] == D('-500')
    assert r['cash'] == D('6099.50')

def test_duplicate_and_conflict(sample):
    merged, duplicates, conflicts = merge(sample, sample)
    assert merged == sample and duplicates == 6 and not conflicts
    merged, duplicates, conflicts = merge(sample, [replace(sample[0], amount=D('100'))])
    assert merged == sample and len(conflicts) == 1
    _, duplicates, _ = merge([], [sample[0], sample[0]])
    assert duplicates == 1

@pytest.mark.parametrize('field,value', [('date','2025-13-01'),('date','2025-1-01'),('amount','-50'),('quantity','0'),('price','NaN'),('fees','-1'),('symbol','AAPL250101C100'),('symbol',''),('currency','EUR'),('transaction_type','SPLIT'),('transaction_type','SHORT')])
def test_invalid_rows(field, value):
    row = dict(transaction_id='x',date='2025-01-01',account='A',source='CSV',symbol='AAPL',transaction_type='BUY',quantity='1',price='100',fees='1',amount='-101',currency='USD')
    row[field] = value
    valid, errors = validate([row])
    assert not valid and errors[0]['row'] == 2

def test_missing_prices(sample):
    r = calculate(sample)
    assert r['total'] is None and r['market_value'] is None
    assert all(h['price'] is None for h in r['holdings'])
    assert r['cash'] == D('6099.50')

def test_unrealized_and_zero_basis():
    q = Quote(D('20'), datetime.now(timezone.utc), 'Manual')
    r = calculate([trade('1','BUY','2','10','1')], prices={'AAPL':q})
    assert r['unrealized'] == D('19')
    r = calculate([trade('1','BUY','2','0')], prices={'AAPL':q})
    assert r['unrealized_pct'] is None

def test_oversell_and_incomplete_history():
    r = calculate([trade('1','BUY','1','100'),trade('2','SELL','2','200')])
    assert r['realized'] is None and r['basis'] is None and r['total'] is None
    assert any('exceeds' in f for f in r['flags'])
    r = calculate([trade('1','BUY','1','100')], history_complete=False)
    assert r['basis'] is None and r['cash'] is None and r['flags']

def test_openings_and_overlap():
    opening = OpeningPosition('A','AAPL',D('2'),D('20'),date(2024,12,31))
    r = calculate([trade('1','SELL','1','20')], [opening], {'A': (D('100'), date(2024,12,31))})
    assert r['realized'] == D('10') and r['cash'] == D('120')
    assert r['holdings'][0]['cost_basis'] == D('10')
    r = calculate([trade('1','SELL','1','20',day='2024-12-31')], [opening])
    assert r['flags'] and r['basis'] is None

def test_export_formula_safety(sample):
    data = export_csv([replace(sample[0], account='=HYPERLINK("bad")', source=' @SUM(1)')])
    assert "'=HYPERLINK" in data and "' @SUM" in data
    assert '-1801' in export_csv(sample)

def test_file_errors_and_mapping():
    with pytest.raises(ValueError):
        read_csv(b'\xff')
    with pytest.raises(ValueError):
        read_csv(b'a,a\n1,2')
    with pytest.raises(ValueError):
        read_csv(b'a,b\n1,2,3')
    _, rows = read_csv(Path('sample_data/transactions.csv').read_bytes())
    rows[0]['ID'] = rows[0].pop('transaction_id')
    valid, errors = validate(rows[:1], {'transaction_id':'ID'})
    assert valid and not errors

def test_opening_import():
    positions, errors = opening_csv(Path('sample_data/opening_positions.csv').read_bytes())
    assert len(positions) == 1 and not errors

def test_broker_unsupported_activity():
    accepted, flags = normalize_transactions([{'transactionId':1,'transactionType':'Transfer','amount':100,'brokerage':{}}, {'transactionId':2,'transactionType':'BUY','amount':-10,'brokerage':{'product':{'symbol':'AAPL','securityType':'OPTN'}}}], 'A')
    assert not accepted and len(flags) == 2
