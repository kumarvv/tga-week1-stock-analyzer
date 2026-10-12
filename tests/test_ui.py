from streamlit.testing.v1 import AppTest

def test_demo_dashboard_and_drilldown():
    app = AppTest.from_file('app.py', default_timeout=30).run()
    assert not app.exception
    next(b for b in app.button if b.label == 'Load demo portfolio').click().run()
    assert not app.exception
    metrics = {m.label:m.value for m in app.metric}
    assert metrics['Cash balance'] == '$6,099.50'
    assert metrics['Realized gain / loss · period'] == '$38.80'
    assert metrics['Total portfolio value'] == '$10,069.50'
    assert len(app.get('plotly_chart')) == 2
    next(b for b in app.button if b.label == 'Open holding transactions in Details').click().run()
    assert not app.exception
    assert app.session_state['focus'] == 'AAPL'
    next(b for b in app.button if b.label == 'Clear imported data').click().run()
    assert not app.exception and not app.session_state['transactions']

def test_sessions_are_isolated():
    first = AppTest.from_file('app.py').run()
    next(b for b in first.button if b.label == 'Load demo portfolio').click().run()
    second = AppTest.from_file('app.py').run()
    assert first.session_state['transactions']
    assert not second.session_state['transactions']
