Tech Stack Document
(Based on standard tech stack canvas/templates from Miroverse and common documentation examples.)
Technology Stack – Quant Bot Clean
Core Language & Runtime

Python 3.12+

Architecture

Hexagonal (Ports & Adapters) – core business logic isolated from external APIs/feeds.

Key Libraries & SDKs (Official Exchange SDKs Mandated)

Exchanges:
Binance.US: binance-connector-python (US endpoints)
Kraken: python-kraken-sdk (preferred) or krakenex
Coinbase (standard): coinbase-python
Coinbase Advanced Trade: coinbase-advanced-py (PEM key handling)

Environment: python-dotenv
Precision: decimal (built-in Decimal)
Data Feeds: Native WebSocket support in SDKs (no CCXT)
Other: Standard library (logging, asyncio if needed), requests (fallback only)

Data Storage

In-memory only (self._cache dicts in managers)
Minimal persistent config: JSON (settings.json, coins.json – skeleton only), .env, to avoid hard values in a dynamic world, bot has to fetch all the data, it should not guess, nor follow a static list!!!

Infrastructure

Deployment: Single process on personal server/laptop
No database
Logging: File-based (logs/trades, errors, performance)

Testing & Utils

(tests/ directory placeholder) we can backtest vs 3 months of historical data we can easily find online and download. 
Utilities: Custom helpers, logger
