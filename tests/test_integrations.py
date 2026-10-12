from datetime import date, datetime, timezone
from unittest.mock import Mock
import pytest
from integrations.etrade import ETrade, BrokerError
from services.reconciliation import broker_report
from services.calculations import calculate
from models import D


def test_transaction_pagination():
    broker = ETrade()
    broker.get = Mock(side_effect=[{'TransactionListResponse': {'Transaction':[{'transactionId':1}], 'next':'https://api.etrade.com/v1/accounts/x/transactions?marker=m&count=50'}}, {'TransactionListResponse':{'Transaction':{'transactionId':2}}}])
    rows = broker.transactions({'accountIdKey':'x'}, date(2025,1,1), date(2025,4,1))
    assert len(rows) == 2
    assert broker.get.call_args.args[1]['marker'] == 'm'

def test_portfolio_pagination_and_repeated_marker():
    broker = ETrade()
    broker.get = Mock(side_effect=[{'BalanceResponse':{}}, {'PortfolioResponse':{'AccountPortfolio':[{'Position':[{'quantity':1}], 'nextPageNo':'2'}]}}, {'PortfolioResponse':{'AccountPortfolio':[{'Position':[{'quantity':2}]}]}}])
    assert len(broker.snapshot({'accountIdKey':'x'})['positions']) == 2
    broker.get = Mock(return_value={'TransactionListResponse':{'marker':'m'}})
    with pytest.raises(BrokerError, match='repeated'):
        broker.transactions({'accountIdKey':'x'}, date(2025,1,1), date(2025,4,1))

def test_expired_authorization_is_sanitized():
    broker = ETrade()
    broker.client = Mock()
    broker.client.get.return_value = Mock(status_code=401)
    with pytest.raises(BrokerError, match='expired'):
        broker.get('/v1/accounts/list.json')

def test_snapshot_preferred_without_inventing_basis():
    snapshots = {'A':{'timestamp':datetime.now(timezone.utc), 'balance':{'Computed':{'cashBalance':100}}, 'positions':[{'Product':{'symbol':'AAPL','securityType':'EQ'}, 'quantity':2, 'marketValue':40}]}}
    result = broker_report(calculate([], history_complete=False), snapshots)
    assert result['total'] == D('140')
    assert result['basis'] is None and result['unrealized'] is None
    assert result['realized'] is None

def test_snapshot_unsupported_positions_incomplete():
    snapshots = {'A':{'timestamp':datetime.now(timezone.utc), 'balance':{'Computed':{'cashBalance':100}}, 'positions':[{'Product':{'symbol':'AAPL','securityType':'OPTN'}, 'quantity':2, 'marketValue':40}]}}
    result = broker_report(calculate([]), snapshots)
    assert result['total'] is None and result['flags']
