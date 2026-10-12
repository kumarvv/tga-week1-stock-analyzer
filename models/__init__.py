from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

D = Decimal
ZERO = D('0')
TYPES = ('BUY', 'SELL', 'DIVIDEND', 'DEPOSIT', 'WITHDRAWAL', 'FEE')
COLUMNS = 'transaction_id,date,account,source,symbol,transaction_type,quantity,price,fees,amount,currency'.split(',')

@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    date: date
    account: str
    source: str
    symbol: str
    transaction_type: str
    quantity: Decimal
    price: Decimal
    fees: Decimal
    amount: Decimal
    currency: str = 'USD'

    @property
    def key(self):
        return self.source, self.account, self.transaction_id

@dataclass(frozen=True)
class OpeningPosition:
    account: str
    symbol: str
    quantity: Decimal
    total_cost_basis: Decimal
    as_of_date: date
    currency: str = 'USD'

@dataclass(frozen=True)
class Quote:
    price: Decimal
    timestamp: datetime
    provider: str
    delayed: bool = False

    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
