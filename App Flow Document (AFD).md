(Based on standard user/system flow templates from Miro, Figma, and Milanote – adapted as system execution flow since minimal user UI; primarily automated bot with console/dashboard monitoring.)
App Flow Document – Quant Bot Clean
Overall System Flow (High-Level)

Startup (main.py)
Load minimal config (.env for keys, sparse settings.json for static params like cache TTL).
Initialize managers → API-first fetch All dynamic values needed: balances, fees, staking products/yields, markets, transfer fees/speed.
Establish WebSocket connections (all 4 exchanges).
Determine current mode (BTC/GOLD) via signals or manual/user input.
Start bots and monitoring loops ( keep in mind not all components need to be started up everytime, some bots lay dormant for months!).

Continuous Operation Loop
Managers refresh dynamic data every 5–10 minutes.
Scanner monitors market context → triggers signals.
Q-Bot runs tight arbitrage scan/execute cycle (10–30s).
A-Bot waits for TradingView signals → buy/stake/sell.
G-Bot active only in GOLD Mode (or during manual monthly sweeps)→ accumulate PAXG.
Money/Transfer managers rebalance as needed (conversion first, transfer second).

Shutdown/Health
Graceful exit on signal; log final state.


User Interaction Flow (Minimal – Operator Focused)

Setup
Create/edit .env with API keys/secrets (including PEM for Coinbase Advanced).
Configure TradingView webhooks.

Launch
Run python main.py.
View console logs, dashboard.py (AND mini_dashboard.py as a new tab) for status (balances, active bots, recent trades, etc.).

Monitoring
Real-time logs (trades, errors, performance).
Dashboard view: Current mode, capital allocation, staking positions, recent opportunities, trigger warnings, etc.

Intervention (Rare)
Manual override buttons over signals. 
Config tweaks, etc. in a user interface tabs/ like settings on any dashboard


Decision Points

High volatility → slow down cycles, raise thresholds.
High latency -> adjust operations according to time critical and non-critical operations.
Capital drift 5-10% → trigger conversion to avoid transfer fees.
Capital drift >15% -> dont wait if low latency and auto transfer enabled. Otherwise send alert for manual transfer and resume operations..
API failure → retry → fallback → warning log (continue if safe).

THERE ARE No UI flows – bot is headless/automated.
need somewhere like a dashboard settings tab to tweak configuration settings if needed during live/backtesting.
