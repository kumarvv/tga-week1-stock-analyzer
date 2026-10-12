from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from models import D, ZERO

@dataclass
class Lot:
    quantity: object
    cost: object
    acquired: date
    transaction_id: str

def calculate(transactions, openings=(), opening_cash=None, as_of=None, start=None, accounts=None, prices=None, history_complete=True):
    end = as_of or date.today()
    start = start or date.min
    selected = lambda a: accounts is None or a in accounts
    lots, cash, sales, flags = defaultdict(list), ZERO, [], []
    unreliable = set()
    if not history_complete:
        flags.append('History is incomplete: reconstructed cash, cost basis and gains may be unavailable. Supply opening balances and positions.')
    for account, entry in (opening_cash or {}).items():
        amount, day = entry
        if selected(account) and day <= end:
            cash += amount
    for o in openings:
        if selected(o.account) and o.as_of_date <= end:
            lots[o.account, o.symbol].append(Lot(o.quantity, o.total_cost_basis, o.as_of_date, 'OPENING'))
    dividends = contributions = ZERO
    for t in sorted(transactions, key=lambda t: t.date):  # stable: same-day input order
        if not selected(t.account) or t.date > end:
            continue
        prior_opening = any(o.account == t.account and o.symbol == t.symbol and t.date <= o.as_of_date for o in openings)
        prior_cash = t.account in (opening_cash or {}) and t.date <= opening_cash[t.account][1]
        if prior_opening or prior_cash:
            flags.append(f'{t.transaction_id}: overlaps opening snapshot. Remove overlapping history or move the snapshot earlier.')
            unreliable.add((t.account, t.symbol))
            continue
        cash += t.amount
        key = (t.account, t.symbol)
        if start <= t.date:
            if t.transaction_type == 'DIVIDEND':
                dividends += t.amount
            elif t.transaction_type in ('DEPOSIT', 'WITHDRAWAL'):
                contributions += t.amount
        if t.transaction_type == 'BUY':
            lots[key].append(Lot(t.quantity, t.quantity * t.price + t.fees, t.date, t.transaction_id))
        elif t.transaction_type == 'SELL':
            available = sum((l.quantity for l in lots[key]), ZERO)
            if t.quantity > available:
                flags.append(f'{t.transaction_id}: sale exceeds available shares ({available}); missing history or unsupported short. Basis and realized gain unavailable.')
                unreliable.add(key)
                sales.append({'transaction_id': t.transaction_id, 'account': t.account, 'source': t.source, 'symbol': t.symbol, 'date': t.date, 'gain': None, 'lots': []})
                continue
            remaining, basis, breakdown = t.quantity, ZERO, []
            while remaining:
                l = lots[key][0]
                q = min(l.quantity, remaining)
                cost = l.cost * q / l.quantity
                breakdown.append({'buy_id': l.transaction_id, 'acquired': l.acquired, 'quantity': q, 'cost_basis': cost})
                basis += cost
                l.quantity -= q
                l.cost -= cost
                remaining -= q
                if not l.quantity:
                    lots[key].pop(0)
            gain = t.amount - basis if history_complete and key not in unreliable else None
            sales.append({'transaction_id': t.transaction_id, 'account': t.account, 'source': t.source, 'symbol': t.symbol, 'date': t.date, 'gain': gain, 'lots': breakdown})
    holdings = []
    for (account, ticker), ls in lots.items():
        quantity = sum((l.quantity for l in ls), ZERO)
        if not quantity:
            continue
        reliable = history_complete and (account, ticker) not in unreliable
        basis = sum((l.cost for l in ls), ZERO) if reliable else None
        quote = (prices or {}).get(ticker)
        value = quantity * quote.price if quote else None
        gain = value - basis if value is not None and basis is not None else None
        holdings.append({'account': account, 'symbol': ticker, 'quantity': quantity, 'average_cost': basis / quantity if basis is not None else None, 'price': quote.price if quote else None, 'market_value': value, 'cost_basis': basis, 'unrealized_gain': gain, 'unrealized_pct': gain / basis * 100 if gain is not None and basis else None, 'quote_timestamp': quote.timestamp.isoformat() if quote else 'Missing', 'price_source': quote.provider if quote else 'Missing', 'delayed': quote.delayed if quote else None})
    complete = history_complete and not unreliable and all(h['market_value'] is not None for h in holdings)
    market_value = sum((h['market_value'] or ZERO for h in holdings), ZERO)
    basis = sum((h['cost_basis'] or ZERO for h in holdings), ZERO) if history_complete and not unreliable else None
    total = market_value + cash if complete else None
    for h in holdings:
        h['portfolio_weight'] = h['market_value'] / total * 100 if total and h['market_value'] is not None else None
    period_sales = [s for s in sales if start <= s['date'] <= end]
    realized = sum((s['gain'] for s in period_sales), ZERO) if history_complete and not unreliable and all(s['gain'] is not None for s in period_sales) else None
    if cash < 0:
        flags.append('Negative reconstructed cash: check opening cash, missing deposits or unsupported margin activity.')
    return dict(holdings=holdings, cash=cash if history_complete and not unreliable else None, known_cash=cash, market_value=market_value if complete else None, total=total, basis=basis, unrealized=market_value-basis if complete and basis is not None else None, unrealized_pct=(market_value-basis)/basis*100 if complete and basis else None, realized=realized, dividends=dividends, contributions=contributions, sales=sales, flags=flags, complete=complete)
