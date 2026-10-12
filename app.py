import os
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from decimal import InvalidOperation
from zoneinfo import ZoneInfo
import streamlit as st
from dotenv import load_dotenv
from models import COLUMNS, TYPES, D, Quote
from services.imports import read_csv, validate, merge, export_csv, opening_csv, number
from services.calculations import calculate
from services.reconciliation import broker_report
from services.pricing import DemoProvider
from integrations.etrade import ETrade, BrokerError
from integrations.base import RobinhoodAdapter
from integrations.normalization import normalize_transactions
from components.dashboard import frame, transaction_frame, money, metrics, charts

load_dotenv()
st.set_page_config(page_title='Stock Portfolio Analyzer', page_icon='📈', layout='wide')
st.title('Stock Portfolio Analyzer')
st.caption('Your holdings, cash and activity in one place • USD • Informational analytics; no trades are executed.')
S = st.session_state
for key, default in dict(transactions=[], openings=[], opening_cash={}, prices={}, demo=False, last_sync=None, broker=None, broker_accounts=[], snapshots={}, broker_flags=[], focus='All symbols', import_report=None).items():
    if key not in S:
        S[key] = default

def reset_data():
    for k, v in dict(transactions=[], openings=[], opening_cash={}, prices={}, demo=False, last_sync=None, snapshots={}, broker_flags=[], import_report=None, focus='All symbols').items():
        S[k] = v

def import_transactions(valid):
    before = len(S.transactions)
    S.transactions, duplicates, conflicts = merge(S.transactions, valid)
    S.last_sync = datetime.now(timezone.utc).isoformat()
    S.import_report = f'Accepted {len(S.transactions)-before} · duplicates {duplicates} · conflicts {len(conflicts)}'
    for conflict in conflicts:
        st.error(conflict)
    st.success(S.import_report)

accounts = sorted({t.account for t in S.transactions} | {o.account for o in S.openings} | set(S.opening_cash))
symbols = sorted({t.symbol for t in S.transactions if t.symbol} | {o.symbol for o in S.openings})
today = datetime.now(ZoneInfo('America/New_York')).date()
with st.sidebar:
    st.header('Portfolio controls')
    selected_account = st.selectbox('Account', ['All accounts'] + accounts)
    earliest = min([t.date for t in S.transactions] + [today])
    dates = st.date_input('Reporting date range', (earliest, today))
    if len(dates) != 2:
        st.info('Choose a start and end date.'); st.stop()
    start, end = dates
    if start > end:
        st.error('Start must be before end.'); st.stop()
    symbol_filter = st.multiselect('Symbol filter', symbols)
    st.caption('Base currency: USD')
    source_names = ', '.join(sorted({t.source for t in S.transactions})) or 'No imported data'
    st.write('Sources: ' + ('DEMO • ' if S.demo else '') + source_names)
    st.write('E*TRADE: ' + ('Authorized' if S.broker and S.broker.authorized else 'Disconnected'))
    st.caption('Last successful import/sync: ' + (S.last_sync or 'Never'))
    if st.button('Refresh quotes', disabled=not symbols):
        try:
            if S.demo:
                S.prices = DemoProvider().quotes(symbols)
            elif S.broker and S.broker.authorized:
                with st.spinner('Refreshing brokerage quotes…'):
                    S.prices.update(S.broker.quotes(symbols))
                    S.last_sync = datetime.now(timezone.utc).isoformat()
            else:
                st.info('Update manual prices in Start / Data Sources.')
        except BrokerError as exc:
            st.error(str(exc))
    if st.button('Disconnect E*TRADE', disabled=S.broker is None):
        try:
            S.broker.disconnect()
            S.broker = None
            S.broker_accounts = []
            reset_data()
            st.rerun()
        except BrokerError as exc:
            st.error(str(exc) + ' Local session retained so you can retry revocation.')
    if st.button('Clear imported data'):
        reset_data(); st.rerun()
if S.demo:
    st.warning('DEMO PORTFOLIO • Synthetic prices dated April 15, 2025. These are not live market prices.')
start_tab, summary_tab, details_tab = st.tabs(['Start / Data Sources', 'Summary', 'Details'])
with start_tab:
    cards = st.columns(3)
    with cards[0], st.container(border=True):
        st.subheader('E*TRADE')
        st.write('OAuth authorization • ' + os.getenv('ETRADE_ENV', 'sandbox').title())
        st.caption('Read account data only. Enter credentials in your local .env; never enter your brokerage password here.')
        if st.button('Start authorization'):
            try:
                S.broker = ETrade()
                S.auth_url = S.broker.authorize()
            except BrokerError as exc:
                st.error(str(exc))
        if S.get('auth_url') and S.broker and not S.broker.authorized:
            st.link_button('Authorize on E*TRADE', S.auth_url)
            verifier = st.text_input('E*TRADE verifier', type='password')
            if st.button('Complete authorization'):
                try:
                    S.broker.verify(verifier)
                    S.broker_accounts = S.broker.accounts()
                    S.pop('auth_url', None)
                    st.rerun()
                except BrokerError as exc:
                    st.error(str(exc))
        if S.broker and S.broker.authorized:
            st.success('Authorized session')
            if st.button('Renew inactive authorization'):
                try:
                    S.broker.renew(); st.success('Renewed.')
                except BrokerError as exc:
                    st.error(str(exc))
            selected_broker = st.multiselect('Accounts to synchronize', range(len(S.broker_accounts)), format_func=lambda i: S.broker_accounts[i].get('accountDesc', f'Account {i+1}'))
            sync_start = st.date_input('Broker history start', today-timedelta(days=365), min_value=today-timedelta(days=729), max_value=today)
            if st.button('Synchronize selected accounts', disabled=not selected_broker):
                try:
                    incoming, snapshots, flags = [], {}, []
                    progress = st.progress(0)
                    for n, i in enumerate(selected_broker):
                        account = S.broker_accounts[i]
                        name = 'E*TRADE ' + str(account['accountIdKey'])
                        snapshots[name] = S.broker.snapshot(account)
                        rows = S.broker.transactions(account, sync_start, today)
                        normalized, warnings = normalize_transactions(rows, name)
                        incoming.extend(normalized); flags.extend(warnings)
                        progress.progress((n+1)/len(selected_broker))
                    S.snapshots.update(snapshots)
                    S.broker_flags = flags
                    S.demo = False
                    S.prices = {}
                    import_transactions(incoming)
                    st.warning('Broker history is bounded. Broker snapshots are shown separately; reconstructed gains require complete opening history.')
                except (BrokerError, ValueError, KeyError):
                    st.error('Synchronization failed. Check authorization, selected dates and broker availability. Previous imported data retained.')
    with cards[1], st.container(border=True):
        st.subheader('Robinhood')
        st.info(RobinhoodAdapter.message)
        st.caption('Official Trading MCP supports stock data, but no approved OAuth/MCP session is configured for this app. No private APIs or crypto substitution.')
        if st.button('Use CSV import'):
            st.info('Upload your transactions using the CSV card to the right.')
    with cards[2], st.container(border=True):
        st.subheader('CSV upload')
        st.write('Preview, map and validate before importing.')
        st.download_button('Download example CSV', Path('sample_data/transactions.csv').read_bytes(), 'transactions.csv', 'text/csv')
        upload = st.file_uploader('Transactions CSV', type=['csv'])
        if st.button('Load demo portfolio'):
            reset_data()
            _, rows = read_csv(Path('sample_data/transactions.csv').read_bytes())
            S.transactions, _ = validate(rows)
            S.prices = DemoProvider().quotes(['AAPL', 'MSFT'])
            S.demo = True
            S.last_sync = datetime.now(timezone.utc).isoformat()
            st.rerun()
    if upload:
        try:
            headers, rows = read_csv(upload.getvalue(), int(os.getenv('CSV_MAX_MB', '5')))
            st.subheader('Preview & column mapping')
            st.dataframe(rows[:20], use_container_width=True)
            mapping = {}
            cols = st.columns(3)
            for i, k in enumerate(COLUMNS):
                with cols[i % 3]:
                    mapping[k] = st.selectbox(k, headers, index=headers.index(k) if k in headers else 0, key='map_'+k)
            valid, errors = validate(rows, mapping)
            st.write(f'Valid: {len(valid)} · rejected: {len(errors)}')
            if errors:
                st.dataframe(errors, use_container_width=True)
            only_valid = st.checkbox('Explicitly import valid rows only; rejected rows remain excluded', disabled=not errors)
            if st.button('Import validated transactions', disabled=not valid or bool(errors and not only_valid)):
                S.demo = False
                S.prices = {k: v for k, v in S.prices.items() if v.provider != 'Synthetic demo'}
                import_transactions(valid)
                if errors:
                    st.warning(f'{len(errors)} invalid rows excluded by your choice. Correct and reimport them.')
        except ValueError as exc:
            st.error(str(exc))
    with st.expander('CSV schema and calculation rules'):
        st.code(','.join(COLUMNS))
        st.write('Dates: YYYY-MM-DD. Stable IDs are unique within source and account. BUY/SELL require positive quantity; fractional shares supported. Prices and fees are nonnegative. BUY net amount = −(quantity × price + fees); SELL = quantity × price − fees; tolerance $0.01. DIVIDEND/DEPOSIT amounts are positive; WITHDRAWAL/FEE negative. Cash-only rows require quantity, price and fees = 0. Symbols required for trades and dividends. USD only. Same-date input order is preserved. Options, shorts, transfers, splits and corporate actions are unsupported.')
    with st.expander('Opening positions & opening cash'):
        st.write('If history starts after account inception, supply known opening positions and cash dated BEFORE your first imported transaction. Do not infer missing cost basis. An opening position is treated as one FIFO lot; gains are estimates if the real opening lot order differs.')
        st.download_button('Opening positions example', Path('sample_data/opening_positions.csv').read_bytes(), 'opening_positions.csv')
        opening_upload = st.file_uploader('Opening positions CSV', type=['csv'], key='opening_upload')
        if opening_upload:
            try:
                positions, errors = opening_csv(opening_upload.getvalue())
                st.dataframe([asdict(p) for p in positions])
                if errors:
                    st.dataframe(errors)
                if st.button('Replace opening positions', disabled=bool(errors) or not positions):
                    S.openings = positions; st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        with st.form('opening_cash_form'):
            cash_account = st.text_input('Opening cash account', value=accounts[0] if accounts else 'Individual')
            cash_value = st.text_input('Opening cash USD', '0.00')
            cash_date = st.date_input('Opening cash as of', earliest-timedelta(days=1))
            if st.form_submit_button('Save opening cash'):
                try:
                    amount = number(cash_value)
                    if not cash_account.strip() or amount < 0:
                        raise ValueError('Account required; long-only opening cash must be nonnegative.')
                    S.opening_cash[cash_account.strip()] = (amount, cash_date); st.rerun()
                except (ValueError, InvalidOperation) as exc:
                    st.error(str(exc))
    with st.expander('Manual prices · offline use', expanded=bool(symbols) and not S.prices):
        st.caption('Manual prices are session-only estimates with entry timestamps. No public alternative provider is configured.')
        if symbols:
            with st.form('manual_prices'):
                values = {s: st.text_input(f'{s} price USD (blank = missing)', str(S.prices[s].price) if s in S.prices and S.prices[s].provider == 'Manual' else '', key='manual_'+s) for s in symbols}
                if st.form_submit_button('Apply manual prices'):
                    try:
                        updated = {}
                        for s, value in values.items():
                            if value.strip():
                                price = number(value)
                                if price < 0:
                                    raise ValueError('Price cannot be negative.')
                                updated[s] = Quote(price, datetime.now(timezone.utc), 'Manual')
                        S.prices.update(updated)
                        for s, value in values.items():
                            if not value.strip() and s in S.prices and S.prices[s].provider == 'Manual':
                                del S.prices[s]
                        st.rerun()
                    except (ValueError, InvalidOperation):
                        st.error('Enter finite, nonnegative numeric prices.')
        else:
            st.info('Import transactions or opening positions first.')

selected_accounts = None if selected_account == 'All accounts' else [selected_account]
complete_history = st.sidebar.checkbox('History starts empty or opening balances are complete', value=not bool(S.snapshots), help='Only enable when all activity since your opening snapshot is imported, including corporate-action adjustments.')
fresh_prices = {k: v for k, v in S.prices.items() if v.provider in ('Manual', 'Synthetic demo') or (datetime.now(timezone.utc) - v.fetched_at).total_seconds() < 300}
report = calculate(S.transactions, S.openings, S.opening_cash, end, start, selected_accounts, fresh_prices if end == today or S.demo else {}, complete_history)
period = [t for t in S.transactions if start <= t.date <= end and (selected_accounts is None or t.account in selected_accounts) and (not symbol_filter or t.symbol in symbol_filter)]
# Summary totals always cover the selected account; symbol filters affect table/activity only.
with summary_tab:
    if not S.transactions and not S.openings:
        st.info('Load the demo or import a portfolio from Start / Data Sources.')
    else:
        st.subheader('Portfolio overview')
        st.caption('Summary totals cover selected accounts. Symbol filters affect holdings table and activity charts; cash stays account-wide.')
        reconstructed = report
        if S.snapshots and end == today:
            view = st.radio('Current balances source', ['Broker snapshot (synchronized accounts only)', 'Reconstructed history'], horizontal=True)
            if view.startswith('Broker'):
                report = broker_report(reconstructed, S.snapshots, selected_accounts)
                st.caption('Current metrics use the latest synchronized broker snapshot. Activity metrics use available transaction history. Refresh by synchronizing again.')
        metrics(report)
        for flag in report['flags']:
            st.warning(flag)
        charts(report, period)
        st.subheader('Holdings')
        holdings = [h for h in report['holdings'] if not symbol_filter or h['symbol'] in symbol_filter]
        st.dataframe(frame(holdings), use_container_width=True, hide_index=True, column_config={k: st.column_config.NumberColumn(k.replace('_', ' ').title(), format='%.2f') for k in ('price','market_value','cost_basis','average_cost','unrealized_gain','unrealized_pct','portfolio_weight')})
        if holdings:
            holding_symbol = st.selectbox('Holding to inspect', sorted({h['symbol'] for h in holdings}))
            if st.button('Open holding transactions in Details'):
                S.focus = holding_symbol
                st.rerun()
            st.caption('Select the Details tab to see the chosen holding’s transactions.')
        st.info('Portfolio value change and cash-flow-adjusted investment return: N/A. Historical prices and verified complete cash-flow history are required.')
        if S.snapshots:
            st.subheader('Broker-reported current positions & reconciliation')
            st.caption('Broker snapshots are authoritative current observations. They do not establish prior FIFO history. No missing cost basis is inferred.')
            rows = []
            for account, snap in S.snapshots.items():
                if selected_accounts and account not in selected_accounts:
                    continue
                for p in snap['positions']:
                    prod = p.get('Product', p.get('product', {}))
                    ticker = prod.get('symbol', '')
                    reconstructed = sum((h['quantity'] for h in reconstructed['holdings'] if h['account'] == account and h['symbol'] == ticker), D('0'))
                    rows.append({'account': account, 'symbol': ticker, 'security_type': prod.get('securityType'), 'broker_quantity': p.get('quantity'), 'broker_cost_basis': p.get('totalCost'), 'broker_market_value': p.get('marketValue'), 'reconstructed_quantity': reconstructed, 'difference': D(str(p.get('quantity', 0))) - reconstructed, 'snapshot_time': snap['timestamp'].isoformat()})
                computed = snap['balance'].get('Computed', snap['balance'].get('computedBalance', {}))
                st.write(account + ' · reported cash: ' + (money(D(str(computed['cashBalance']))) if 'cashBalance' in computed else 'N/A'))
            st.dataframe(frame(rows), use_container_width=True)
with details_tab:
    st.subheader('Transaction explorer')
    st.caption('Signed transaction amounts sum to cash flow, not profit. Click table headers to sort; use the table search toolbar for quick inspection.')
    filter_cols = st.columns(4)
    with filter_cols[0]:
        types = st.multiselect('Transaction types', TYPES)
    with filter_cols[1]:
        sources = st.multiselect('Sources', sorted({t.source for t in S.transactions}))
    with filter_cols[2]:
        focus_options = ['All symbols'] + symbols
        if S.focus not in focus_options:
            S.focus = 'All symbols'
        focus = st.selectbox('Holding history', focus_options, key='focus')
    with filter_cols[3]:
        search = st.text_input('Search all transaction fields')
    filtered = [t for t in period if (not types or t.transaction_type in types) and (not sources or t.source in sources) and (focus == 'All symbols' or t.symbol == focus) and (not search or search.casefold() in ' '.join(map(str, asdict(t).values())).casefold())]
    st.write(f'{len(filtered)} transactions · signed cash flow {money(sum((t.amount for t in filtered), D("0")))}')
    st.dataframe(transaction_frame(filtered), use_container_width=True, hide_index=True)
    st.download_button('Download filtered CSV', export_csv(filtered), 'filtered_transactions.csv', 'text/csv')
    if filtered:
        index = st.selectbox('Transaction detail', range(len(filtered)), format_func=lambda i: f'{filtered[i].date} · {filtered[i].symbol or "Cash"} · {filtered[i].account} · {filtered[i].transaction_id}')
        t = filtered[index]
        st.json({k: str(v) for k, v in asdict(t).items()})
        sale = next((s for s in report['sales'] if (s['source'], s['account'], s['transaction_id']) == t.key), None)
        if sale:
            st.metric('FIFO realized gain/loss', money(sale['gain']))
            st.dataframe(frame(sale['lots']), use_container_width=True)
        if t.symbol:
            st.write('Complete available symbol history in this account (before period filtering)')
            st.dataframe(transaction_frame([r for r in S.transactions if r.account == t.account and r.symbol == t.symbol]), use_container_width=True, hide_index=True)
    else:
        st.info('No transactions match these filters.')
    with st.expander('Data quality & reconciliation', expanded=bool(report['flags'] or S.broker_flags)):
        for flag in report['flags']:
            st.warning(flag)
        if S.broker_flags:
            st.dataframe(S.broker_flags)
        if not report['flags'] and not S.broker_flags:
            st.write('No detected calculation flags. CSV validation cannot verify that omitted history or corporate actions are complete.')
