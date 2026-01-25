Product Name: Quant Bot Clean – Cryptocurrency Arbitrage, Staking & Hedging Bot
Version: 1.0 (Post-Refactor API-First)
Date: January 2026
Author: Internal Development (based on repository refactoring goals)
Status: Planning/Refactor
1. Product Overview
Quant Bot Clean is an automated, self-contained cryptocurrency trading bot that exploits arbitrage opportunities (cross-exchange and triangular), manages staking positions, optimizes fund transfers, and hedges with gold-backed assets (PAXG). It operates across four US-compliant exchanges: Binance.US, Kraken, Coinbase (standard), and Coinbase Advanced Trade. The bot is fully API-driven, fetching dynamic operational data (fees, balances, yields, network costs) directly from exchange APIs on startup and periodically, with configuration files used only as minimal fallbacks.
2. Goals & Objectives

Maximize risk-adjusted returns on small capital $10,000 capital through low-risk arbitrage and high-yield staking.
Eliminate hardcoded/static configuration as primary truth source.
Achieve near-zero manual intervention after initial API key setup.
Adapt dynamically to exchange changes (fee tiers, staking products, network costs).
Maintain capital distribution across exchanges with minimal costly transfers.
Support two macro modes (BTC Mode: arbitrage + staking; GOLD Mode: PAXG hedging) driven by external TradingView signals.

3. Target Users

Single operator (bot owner/trader) running on a personal server/laptop.
No public users – internal tool only.

4. Key Features

Arbitrage Execution (Q-Bot): Cross-exchange and triangular opportunities with MIN profit threshold =>0.5% after fees/slippage; dynamic pair discovery via load_markets().
Accumulation & Staking (A-Bot): Responds to TradingView buy/sell signals; auto-stakes highest-APY coins discovered via API (up to 6 positions).
Gold Hedging (G-Bot): In GOLD Mode, accumulates PAXG and sweeps profits to cold storage.
Dynamic Data Fetching: Fees, balances, staking yields/APRs, withdrawal/deposit networks – all via official SDKs on init and refresh.
Optimal Transfer Routing: Live cost analysis across networks; prefers intra-exchange conversions to avoid transfers.
WebSocket Real-Time Feeds: From all four exchanges (including Coinbase Advanced Trade).
Risk Management: Volatility-adaptive thresholds, order book depth checks, health monitoring.
Mode & Signal Handling: TradingView webhook integration for mode flips and A-Bot triggers.

5. Non-Functional Requirements

Hexagonal (ports-and-adapters) architecture preserved.
Precision: All monetary calculations use Decimal.
Reliability: 3-retry exponential backoff on API calls; safe fallbacks only.
Performance: WebSocket-only for real-time data; in-memory caching (5–10 min TTL).
Logging: Comprehensive "Fetched X from API" audit trail.
Security: API keys via .env (PEM handling for Coinbase Advanced).

6. Constraints & Assumptions

Capital: ~$9,000–$10,000 USD equivalent.
Exchanges limited to four specified.
No third-party data sources – only official exchange APIs.
Runs as background process (main.py); optional simple dashboard viewing.

7. Success Metrics

20 distinct "Fetched from API" logs on startup.
Zero hardcoded coin/fee/APR lists in production code.
Profitable arbitrage execution with <15% capital drift across exchanges.
Uptime >99% with graceful fallback on API failures.
