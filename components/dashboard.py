from dataclasses import asdict
from decimal import Decimal
import pandas as pd
import plotly.express as px
import streamlit as st


def frame(rows):
    return pd.DataFrame([{k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in rows])

def transaction_frame(rows):
    return frame([asdict(t) for t in rows])

def money(value):
    return 'N/A' if value is None else f'${value:,.2f}'

def metrics(result):
    st.caption('AS OF END DATE • Holdings use available quotes, not historical end-date prices. For historical end dates, market-value metrics are unavailable.')
    for columns, keys in [(st.columns(4), [('Total portfolio value', 'total'), ('Holdings market value', 'market_value'), ('Cash balance', 'cash'), ('Remaining cost basis', 'basis')]), (st.columns(4), [('Unrealized gain / loss', 'unrealized'), ('Realized gain / loss · period', 'realized'), ('Dividends · period', 'dividends'), ('Net contributions · period', 'contributions')])]:
        for col, (label, key) in zip(columns, keys):
            value = result[key]
            with col:
                delta = ('Gain' if value >= 0 else 'Loss') + f' {money(abs(value))}' if key in ('unrealized', 'realized') and value is not None else None
                st.metric(label, money(value), delta=delta, delta_color='normal' if value is None or value >= 0 else 'inverse')
    st.caption('Unrealized gain/loss: ' + ('N/A' if result['unrealized_pct'] is None else f"{result['unrealized_pct']:+.2f}%") + ' • N/A means missing price, basis or reliable history.')

def charts(result, transactions):
    left, right = st.columns(2)
    h = frame(result['holdings'])
    with left:
        st.subheader('Allocation')
        kind = st.selectbox('Allocation chart', ['Donut', 'Pie', 'Bar'])
        include_cash = st.checkbox('Include cash', True)
        top = st.slider('Top holdings', 1, 20, 8)
        rows = []
        if not h.empty:
            rows = h.dropna(subset=['market_value']).groupby('symbol')['market_value'].sum().sort_values(ascending=False).reset_index().to_dict('records')
        if include_cash and result['cash'] is not None and result['cash'] > 0:
            rows.append({'symbol': 'Cash', 'market_value': float(result['cash'])})
        rows = sorted(rows, key=lambda r: r['market_value'], reverse=True)
        if len(rows) > top:
            rows = rows[:top] + [{'symbol': 'Other', 'market_value': sum(r['market_value'] for r in rows[top:])}]
        df = pd.DataFrame(rows)
        if not df.empty and df.market_value.sum() > 0:
            fig = px.bar(df, x='symbol', y='market_value') if kind == 'Bar' else px.pie(df, names='symbol', values='market_value', hole=.55 if kind == 'Donut' else 0)
            st.plotly_chart(fig, use_container_width=True)
            if not result['complete']:
                st.warning('Partial allocation: missing prices or unreliable balances are excluded.')
        else:
            st.info('Enter prices to see holdings allocation.')
    with right:
        st.subheader('Performance & activity')
        dataset = st.selectbox('Dataset', ['Unrealized gain/loss by symbol', 'Monthly dividends', 'Monthly deposits and withdrawals', 'Portfolio value over time'])
        if dataset == 'Portfolio value over time':
            st.info('N/A: daily historical prices and verified corporate-action history are unavailable. Current holdings are never applied backward.')
            return
        options = ['Bar'] if dataset.startswith('Unrealized') else ['Grouped bar'] if 'deposits' in dataset else ['Bar', 'Line']
        kind = st.selectbox('Activity chart', options)
        if dataset.startswith('Unrealized'):
            df = h.dropna(subset=['unrealized_gain']) if not h.empty else pd.DataFrame()
            if not df.empty:
                df = df.groupby('symbol', as_index=False)['unrealized_gain'].sum()
                df['result'] = df.unrealized_gain.map(lambda v: 'Gain' if v >= 0 else 'Loss')
                fig = px.bar(df, x='symbol', y='unrealized_gain', color='result', color_discrete_map={'Gain': '#087f8c', 'Loss': '#c2413b'})
            else:
                st.info('Reliable basis and prices are required.'); return
        else:
            types = ('DIVIDEND',) if 'dividends' in dataset else ('DEPOSIT', 'WITHDRAWAL')
            rows = [{'month': t.date.strftime('%Y-%m'), 'type': t.transaction_type, 'amount': float(t.amount)} for t in transactions if t.transaction_type in types]
            if not rows:
                st.info('No matching activity in this period.'); return
            df = pd.DataFrame(rows).groupby(['month', 'type'], as_index=False)['amount'].sum()
            fig = px.line(df, x='month', y='amount', color='type', markers=True) if kind == 'Line' else px.bar(df, x='month', y='amount', color='type', barmode='group')
        st.plotly_chart(fig, use_container_width=True)
