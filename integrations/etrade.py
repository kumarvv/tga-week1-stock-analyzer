import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote, urlparse, parse_qs
import requests
from requests_oauthlib import OAuth1Session
from models import Quote, D

class BrokerError(Exception):
    pass

def sequence(value):
    return value if isinstance(value, list) else [value] if value else []

class ETrade:
    """Documented GET-only E*TRADE OAuth/account adapter; owned by one session."""
    def __init__(self):
        self.key = os.getenv('ETRADE_CONSUMER_KEY', '')
        self.secret = os.getenv('ETRADE_CONSUMER_SECRET', '')
        self.sandbox = os.getenv('ETRADE_ENV', 'sandbox') != 'production'
        self.base = 'https://apisb.etrade.com' if self.sandbox else 'https://api.etrade.com'
        self.oauth_base = 'https://api.etrade.com'
        self.client = None
        self.authorized = False
    def authorize(self):
        if not self.key or not self.secret:
            raise BrokerError('Set ETRADE_CONSUMER_KEY and ETRADE_CONSUMER_SECRET, then restart the app.')
        self.client = OAuth1Session(self.key, client_secret=self.secret, callback_uri='oob')
        try:
            token = self.client.fetch_request_token(self.oauth_base + '/oauth/request_token', method='GET', timeout=20)
            return 'https://us.etrade.com/e/t/etws/authorize?' + urlencode({'key': self.key, 'token': token['oauth_token']})
        except Exception:
            raise BrokerError('Authorization could not start. Check environment/key pairing and retry.') from None
    def verify(self, verifier):
        try:
            self.client.fetch_access_token(self.oauth_base + '/oauth/access_token', verifier=verifier.strip(), method='GET', timeout=20)
            self.authorized = True
        except Exception:
            raise BrokerError('Verifier rejected or expired. Start authorization again.') from None
    def get(self, path, params=None, oauth=False):
        if not self.client:
            raise BrokerError('Authorize first.')
        for attempt in range(3):
            try:
                r = self.client.get((self.oauth_base if oauth else self.base) + path, params=params, headers={'Accept': 'application/json'}, timeout=20)
            except requests.RequestException:
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise BrokerError('Broker request timed out or failed. Retry synchronization.') from None
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(min(2, attempt + 1))
                continue
            if r.status_code in (401, 403):
                raise BrokerError('Authorization expired or access denied. Renew or reconnect your session.')
            if r.status_code == 204:
                return {}
            if not r.ok:
                raise BrokerError(f'Broker returned HTTP {r.status_code}. Check access and retry.')
            if oauth:
                return {}
            try:
                return r.json()
            except ValueError:
                raise BrokerError('Broker returned an unreadable response.') from None
        raise BrokerError('Rate limit or broker outage. Retry later.')
    def accounts(self):
        return sequence(self.get('/v1/accounts/list.json').get('AccountListResponse', {}).get('Accounts', {}).get('Account'))
    def snapshot(self, account):
        key = quote(str(account['accountIdKey']), safe='')
        balance = self.get(f'/v1/accounts/{key}/balance.json', {'instType': 'BROKERAGE', 'realTimeNAV': 'true'})
        positions = []
        page = 1
        for _ in range(200):
            data = self.get(f'/v1/accounts/{key}/portfolio.json', {'count': 50, 'pageNumber': page, 'view': 'COMPLETE', 'lotsRequired': 'true'})
            portfolios = sequence(data.get('PortfolioResponse', {}).get('AccountPortfolio'))
            for p in portfolios:
                positions.extend(sequence(p.get('Position')))
            next_page = next((p.get('nextPageNo') for p in portfolios if p.get('nextPageNo')), None)
            if not next_page:
                return {'balance': balance.get('BalanceResponse', {}), 'positions': positions, 'timestamp': datetime.now(timezone.utc)}
            if int(next_page) <= page:
                raise BrokerError('Portfolio pagination did not advance; synchronization aborted.')
            page = int(next_page)
        raise BrokerError('Portfolio exceeded pagination limit; synchronization aborted.')
    def transactions(self, account, start, end):
        key = quote(str(account['accountIdKey']), safe='')
        params = {'startDate': start.strftime('%m%d%Y'), 'endDate': end.strftime('%m%d%Y'), 'sortOrder': 'ASC', 'count': 50}
        rows, seen = [], set()
        for _ in range(200):
            data = self.get(f'/v1/accounts/{key}/transactions.json', params).get('TransactionListResponse', {})
            rows.extend(sequence(data.get('Transaction')))
            marker = data.get('marker')
            if not marker and data.get('next'):
                # Follow only documented marker, never a broker-supplied URL.
                marker = parse_qs(urlparse(data['next']).query).get('marker', [None])[0]
            if not marker:
                return rows
            if marker in seen:
                raise BrokerError('Transaction pagination repeated; synchronization aborted.')
            seen.add(marker)
            params['marker'] = marker
        raise BrokerError('History exceeded pagination limit; narrow the requested period.')
    def quotes(self, symbols):
        result = {}
        for offset in range(0, len(symbols), 25):
            names = ','.join(quote(s, safe='.-') for s in symbols[offset:offset+25])
            data = self.get(f'/v1/market/quote/{names}.json', {'detailFlag': 'ALL'})
            for q in sequence(data.get('QuoteResponse', {}).get('QuoteData')):
                product, fields = q.get('Product', {}), q.get('All', {})
                price = fields.get('lastTrade')
                if price is not None:
                    result[product['symbol']] = Quote(D(str(price)), datetime.fromtimestamp(int(q['dateTimeUTC']), timezone.utc), 'E*TRADE', q.get('quoteStatus') != 'REALTIME')
        return result
    def renew(self):
        self.get('/oauth/renew_access_token', oauth=True)
    def disconnect(self):
        if self.authorized:
            self.get('/oauth/revoke_access_token', oauth=True)
        self.client = None
        self.authorized = False
