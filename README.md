# Stock Portfolio Analyzer

A local Streamlit dashboard for long-only stocks and ETFs, using USD. CSV and demo modes work without brokerage credentials. This app provides informational analytics and has no trading methods.

## Run locally

Python 3.11+ with OpenSSL is recommended. Python 3.9 also runs the CSV/demo app, but Apple's system Python uses LibreSSL and emits an urllib3 compatibility warning; use a modern Python before testing broker HTTPS access.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open http://localhost:8501. On Windows, activate with `.venv\Scripts\activate`. VS Code users can select the virtual environment interpreter and run the **Launch portfolio analyzer** task.

```sh
python -m pytest
```

Optional local configuration:

```sh
cp .env.example .env
```

Edit `.env` to set `ETRADE_CONSUMER_KEY`, `ETRADE_CONSUMER_SECRET`, and `ETRADE_ENV=sandbox` (or `production`). Restart after changing environment variables. `CSV_MAX_MB` defaults to 5; also change `.streamlit/config.toml`'s server upload limit if increasing the application limit.

## Use the dashboard

1. **Start / Data Sources:** Load demo portfolio, or download and upload `sample_data/transactions.csv`. Preview the data and map headers, then import validated rows. Errors show CSV line numbers. An invalid file cannot be imported unless you explicitly choose valid rows only.
2. For real CSV data, expand **Manual prices**, enter current USD prices and apply. Missing quotes stay missing, never zero. Demo prices are deterministic synthetic values (AAPL $215, MSFT $450), dated April 15, 2025.
3. Select account/date range/symbols in the sidebar. Current holdings and cost basis use all available history through the end date; activity metrics use the selected period. Account totals remain account-wide; symbol filters affect tables and activity charts.
4. **Summary:** See eight metrics, unrealized percentage, configurable allocation and activity charts, and holdings with quote timestamps and manual/demo/delay labels. Plotly provides hover, zoom and image export. Use **Open holding transactions in Details**, then select Details.
5. **Details:** Filter types, sources, symbol history and free text. Sort columns, inspect one transaction, see FIFO purchase-lot consumption for sales and download a sanitized CSV. Transaction cash-flow sums are not profit.
6. **Clear imported data** removes portfolio data, prices and snapshots from the current session. **Disconnect E*TRADE** attempts token revocation, then clears private local data. If revocation fails, retry; clearing imported data does not revoke authorization.

Data is in Streamlit session state, with no persistence or shared private-data cache. Reloading/reconnecting can lose your session. Keep your original files.

## CSV contract

```csv
transaction_id,date,account,source,symbol,transaction_type,quantity,price,fees,amount,currency
```

- UTF-8, optional BOM. Unique headers and consistent row lengths. Dates strictly `YYYY-MM-DD`.
- Stable transaction IDs unique within **source + account**. Repeat imports are idempotent. Conflicting content for an existing ID is reported and the original retained. Do not change source/account labels on repeat imports.
- Types: BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, FEE. Cash-only rows require quantity, price and fees equal to zero.
- BUY/SELL require positive quantities (fractional shares allowed) and nonnegative prices/fees. Net signed amount: BUY `−(quantity × price + fees)`, SELL `quantity × price − fees`. Absolute rounding tolerance: $0.01.
- DIVIDEND/DEPOSIT amounts must be positive. WITHDRAWAL/FEE negative. Symbols required for trades/dividends and optional for cash activity. Stock ticker syntax is checked, including rejection of recognizable option-contract symbols; syntax alone cannot verify instrument identity.
- USD only; other currencies are rejected, with no implicit conversion.
- Same-date input order is preserved across imports. Import chronological files in the intended within-day order.
- Fees embedded in trades must not also be separate FEE rows; that would double-count them.
- Options, shorts, transfers, splits and corporate actions are rejected or flagged. Omitted corporate actions cannot be detected from a CSV without external reconciliation.

Opening positions use:

```csv
account,symbol,quantity,total_cost_basis,as_of_date,currency
```

Upload to **Opening positions & opening cash**. This replaces the opening-position set. Enter opening cash per account separately. Use snapshots dated **before** the earliest imported transaction. Overlapping history is flagged and calculations become unavailable. For history starting from a non-empty account, you must supply opening shares, known total cost basis and cash. An opening position becomes one FIFO lot; its average basis does not reproduce an unknown original tax-lot ordering. No missing cost basis is inferred. Uncheck the history-completeness control until the baseline is complete. Unsupported/omitted history makes calculations estimates even if no automatic flag is present.

## Financial definitions

- Holdings: opening shares + purchases − sales, separately by account and symbol.
- Cash: opening cash + signed net cash amounts. Purchase/sale fees are already in net amounts and are not deducted again.
- FIFO purchase basis includes fees. Partial sales proportionally consume each lot's cost and preserve the remainder. Sale gains = net proceeds − consumed basis. Dividends are separate income, not trading gains.
- Remaining average cost = remaining basis / shares. Market value = shares × available quote. Unrealized gain = market value − remaining basis; percentage = gain / remaining basis × 100. Zero denominators display N/A.
- Net external contributions = deposits + negative withdrawals, excluding dividends and trades.
- Oversales flag unavailable basis/gains and totals; the app does not invent short positions or missing lots. Negative cash flags missing funding or unsupported margin activity.
- Missing prices make portfolio totals incomplete. Partial allocation can display known-priced holdings with a warning.
- For historical reporting end dates, quote-dependent metrics are unavailable rather than treating today's quote as a historical quote. Demo quotes are explicitly synthetic snapshots.
- Historical portfolio value, value change and cash-flow-adjusted returns remain N/A: no daily historical-price/corporate-action provider is configured. The app never applies today's holdings backward through history or labels balance changes as investment returns.

For the supplied sample: AAPL 8 shares; MSFT 5 shares; cash $6,099.50; remaining AAPL basis $1,440.80; realized AAPL gain $38.80. Synthetic demo total value: $10,069.50.

## E*TRADE integration

Official references reviewed October 10, 2026:

- [OAuth guide and token lifecycle](https://developer.etrade.com/getting-started/developer-guides)
- [Request token](https://apisb.etrade.com/docs/api/authorization/request_token.html)
- [Account transactions and pagination](https://apisb.etrade.com/docs/api/account/api-transaction-v1.html)
- [Portfolio positions](https://apisb.etrade.com/docs/api/account/api-portfolio-v1.html)
- [Balances](https://apisb.etrade.com/docs/api/account/api-balance-v1.html)
- [Quotes](https://apisb.etrade.com/docs/api/market/api-market-v1.html)
- [Revocation](https://apisb.etrade.com/docs/api/authorization/revoke_access_token.html)

Obtain sandbox consumer credentials through the E*TRADE developer program. Configure matching sandbox keys and environment. Start authorization, follow the E*TRADE link, sign in **on E*TRADE**, consent, then paste the verifier into the local app. Request tokens last five minutes. OAuth uses HMAC-SHA1 and `oob`. Authorization endpoints use `api.etrade.com`; sandbox account data uses `apisb.etrade.com`. Tokens become inactive after two hours and expire at midnight Eastern; renew inactive authorization or reconnect after expiry.

Select authorized accounts and synchronize. The adapter retrieves balances, paginated positions and bounded transaction history (up to 729 days). It uses 20-second request timeouts, at most three GET attempts and 200 pages, and sanitizes API errors. New sync results are fetched before replacing session snapshots. Only explicit supported activity types with verified equity metadata and consistent amounts are imported. Ambiguous transfers and unsupported activity appear in data-quality flags rather than being guessed from descriptions.

Broker snapshots are preferred for current synchronized-account metrics; missing broker basis stays N/A. Reconstructed history is available as an alternate view. The reconciliation table compares broker and reconstructed share quantities. Broker snapshots do not establish historical FIFO lots, so realized gains remain unavailable until history and opening balances are complete. Reported broker cash is not treated as opening cash.

Broker quote results are kept per session for 300 seconds from fetch time. Quote timestamps and delay status remain provider supplied. Refresh explicitly; expired prices are omitted. Manual/demo prices remain until replaced or cleared. No public external quote provider or shared market cache is enabled; `services/pricing.py` exposes the configurable provider protocol.

**Verification status:** adapter routes, pagination, expired authorization and snapshot handling are tested using fixtures/mocks. Neither sandbox nor production authentication or data retrieval has been verified with actual credentials. API JSON casing, transaction categories and pagination behavior should be confirmed against a credentialed sandbox before relying on it for a real portfolio. Broker quotes also remain unverified.

## Robinhood integration status

Robinhood now documents an [official Trading MCP with OAuth and stock-account data](https://robinhood.com/us/en/support/articles/onboarding-an-external-agent/). That supported product is distinct from its [crypto API](https://docs.robinhood.com/). No authorized approved MCP client/session or credentials are available in this application configuration, so the app displays:

> Direct Robinhood stock account connection is unavailable in this configuration. Import your transactions using CSV.

No private endpoints, passwords, scraping, mocked connection or crypto-account substitution are used. `integrations/base.py` documents the future supported adapter interface. A future integration needs approved OAuth/MCP access, verified response schemas and read-only tool allowlisting; this app does not provide that connector yet.

## Security and project map

Financial data, access tokens and broker objects are session-only. Application keys come from environment variables. `.env`, tokens, private imports, caches and Streamlit secrets are ignored by Git. Error UI avoids raw broker responses. Text cells beginning with spreadsheet formula prefixes are apostrophe-escaped on CSV export; genuine numeric signed amounts remain numeric. The app has no login layer and is intended for local use. Multi-user hosting requires authentication and a deployment review.

- `models/`: normalized transactions, opening positions and quotes.
- `services/calculations.py`: Decimal FIFO and portfolio calculations.
- `services/imports.py`: validation, mapping, duplicate handling and safe exports.
- `services/pricing.py`: manual/demo provider interface.
- `services/reconciliation.py`: broker-reported current metrics.
- `integrations/`: read-only brokerage interfaces, OAuth adapter and conservative normalization.
- `components/dashboard.py`: metric and Plotly panels.
- `app.py`: session state, source workflows and three tabs.
- `tests/`: calculation/import, adapter and Streamlit interaction tests.

Local verification: pytest covers sample acceptance, multiple/partial FIFO lots, account isolation, fractions, fees, income/contributions, duplicate/conflicting imports, row errors, mapping, missing prices, incomplete history, oversales, baseline overlap, export safety, broker pagination and unavailable basis. Streamlit AppTest covers demo metrics, two chart panels, holding drill-down, clear-data behavior and session isolation. Server startup and health are verified separately. Browser visual inspection was blocked by missing computer-use permissions.
