Backend Structure – API Architecture and Database Schema

Backend Structure Document – Quant Bot Clean
Architecture Overview

Pattern: Hexagonal (Ports & Adapters)
Domain/Core: Pure business logic (no I/O)
Adapters: Exchange implementations and data feeds
Managers: Coordination/orchestration
Bots: Lightweight strategy runners


Directory Structure

domain/: Entities (Trade, Position, Signal), Value Objects (Price, Amount), Aggregates (ArbOpportunity, Balance)
core/: Profit calculation, thresholds, health monitoring, order execution, auction logic
adapters/:
  data/ws.py, feed.py: WebSocket feeds
  exchanges/*.py: Official SDK wrappers (binanceus.py, kraken.py, coinbase.py, coinbase_advanced.py)
manager/: fee.py, money.py, staking.py, transfer.py, scanner.py, signals.py, mode.py, conversion.py
bot/: Q.py (arbitrage), A.py (accumulation/staking), G.py (hedging)
config/: Minimal .env + sparse JSON
ports/: Inbound/outbound interfaces (placeholder)

API Architecture

No Public API – internal only.
External APIs: REST + WebSocket via official SDKs.
Init: fetch_balances(), fetch_fees(), fetch_staking_products(), load_markets()
Real-time: WebSocket tickers/order books (all 4 exchanges)

Internal Flow: Managers call adapters via ports → pure core logic → execution back through adapters.

Database Schema

None – fully in-memory.
State held in manager instances and caches.
Persistent: Only logs and minimal config files.

This structure ensures testability, adaptability, and strict separation of dynamic API concerns from core strategy.

please refer to quant_bot_final <- salvaged version (but uses hard fixed values doesnt fetch live data!!!)
and
QB - failed attempt at removing hard fixed values in quant_bot final ai removed too much!!! 
