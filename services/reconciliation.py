from models import D, ZERO

def broker_report(reconstructed, snapshots, accounts=None):
    """Current broker balances override reconstructed values, never historical activity."""
    result = dict(reconstructed)
    holdings, flags = [], list(reconstructed['flags'])
    cash, cash_complete, basis_complete, price_complete = ZERO, True, True, True
    found = False
    for account, snapshot in snapshots.items():
        if accounts and account not in accounts:
            continue
        found = True
        balance = snapshot['balance']
        computed = balance.get('Computed', balance.get('computedBalance', {}))
        reported_cash = computed.get('cashBalance')
        if reported_cash is None:
            cash_complete = False
        else:
            cash += D(str(reported_cash))
        for p in snapshot['positions']:
            product = p.get('Product', p.get('product', {}))
            ticker, quantity = product.get('symbol', ''), D(str(p.get('quantity', 0)))
            if product.get('securityType') != 'EQ' or quantity < 0 or p.get('positionType', '').upper() == 'SHORT':
                flags.append('Unsupported broker position (non-equity or short); totals incomplete.')
                basis_complete = price_complete = False
                continue
            if not quantity:
                continue
            basis = D(str(p['totalCost'])) if p.get('totalCost') is not None else None
            value = D(str(p['marketValue'])) if p.get('marketValue') is not None else None
            price = D(str(p['price'])) if p.get('price') is not None else (value/quantity if value is not None else None)
            basis_complete &= basis is not None
            price_complete &= value is not None
            gain = value-basis if value is not None and basis is not None else None
            holdings.append(dict(account=account, symbol=ticker, quantity=quantity, average_cost=basis/quantity if basis is not None else None, price=price, market_value=value, cost_basis=basis, unrealized_gain=gain, unrealized_pct=gain/basis*100 if gain is not None and basis else None, quote_timestamp=str(p.get('dateTimeUTC', 'Broker snapshot: '+snapshot['timestamp'].isoformat())), price_source='Broker snapshot', delayed=p.get('quotestatus', 'UNKNOWN') != 'REALTIME'))
    complete = found and cash_complete and price_complete
    mv = sum((h['market_value'] or ZERO for h in holdings), ZERO) if price_complete and found else None
    basis = sum((h['cost_basis'] or ZERO for h in holdings), ZERO) if basis_complete and found else None
    total = mv+cash if complete else None
    for h in holdings:
        h['portfolio_weight'] = h['market_value']/total*100 if h['market_value'] is not None and total else None
    result.update(holdings=holdings, flags=flags, cash=cash if cash_complete and found else None, market_value=mv, total=total, basis=basis, unrealized=mv-basis if mv is not None and basis is not None else None, unrealized_pct=(mv-basis)/basis*100 if mv is not None and basis else None, complete=complete)
    return result
