_FIXED is the only working branch

## Project Goal & Hexagonal Refactor Instructions
This is a cryptocurrency arbitrage and hedging bot designed for a ~$10,000 budget in January 2026.

### Core Strategy (100% to be preserved)
Crypto Arbitrage Strategy: Exploiting Market Inefficiencies for Consistent Returns

The system operates in two primary modes based on a custom TradingView signal:

Macro Signal:
	* Fired (BUY BTC/SELL PAXG) on Nov 2023 = BTC Mode
	* Fired another signal on Nov 2025 (SELL BTC/BUY PAXG) = GOLD Mode.
Capital Allocation:
	* BTC Mode: 85% → [[Q-Bot]], 15% → [[A-Bot]], 0% → [[G-Bot]]
	* GOLD Mode: 15% → [[Q-Bot]], 0% → [[A-Bot]], 85% → [[G-Bot]]
System Components
1. [SIGNAL RECEIVER]
	* Listens for TradingView alerts (Macro Signal (mode flip) AND A-Bot (buy/sell) signals.
	* When something arrives, it immediately tells the Mode Manager or A-Bot when to buy/sell not what to do.
	* One job: Listens for TradingView alerts and passes them on. No polling, no timing.
2. [MODE MANAGER]
	* Holds the current state: BTC mode or GOLD mode.
	* Only changes when the [SIGNAL RECEIVER] tells it to (from Macro Signal).
	* Tells [MONEY MANAGER] which mode is active now.
	* Activates/deactivates bots according to BTC Mode or GOLD Mode
	* One job: remember the mode and announce/apply changes.
5. [MONEY MANAGER]
	* Tracks every penny.
	* Divides the capital.
	* Checks account balances periodically (every few minutes).
	* If money is too uneven between exchanges (>15% drift), signals [TRANSFER MANAGER] AND [CONVERSION MANAGER] to move stablecoins to even it out (cheapest way).
	* Maintains a min dynamic BNB balance (logic already done).
	* Tells [TRANSFER MANAGER] AND [CONVERSION MANAGER] what it needs to maintain the ideal portfolio proportions across accounts for arbitrage, staking and gold sweeps!
	* One job: prevent capital from getting stuck in one account, divide and protect the shared fuel.
6. [CONVERSION MANAGER]
	* It is responsible for all conversions from one form of money to another outside triangular arbitrage.
	* It is basically an on demand triangular arbitrage machine with specified pairs and finds the cheapest AND fastest routes for the [MONEY MANAGER].
	* It tries to keep the drift across accounts below 15% by intra-exchange triangular conversions, so [[Q-bot]] runs smoothly.
	* Does not interrupt arbitrage system
	* One job: Reduces the amount needed to transfer by prioritizing triangular conversions (intra-exchange) over any cross-account transfers whenever possible to eliminate 		transfer fees entirely.
7. [TRANSFER MANAGER]
	* Transfers money across accounts after calculating the speed of transfer and transfer fees across accounts
	* Receives transfer route from [CONVERSION MANAGER].
	* Does not interrupt arbitrage system
	* Always queries real-time network fees & times, at execution time and select the cheapest + fastest shared network between sender/receiver eg:
	* For Kraken → Binance (USDT): Prefer Tron (TRC-20) or Solana → ~$0.50-1 fee, <5 min.
	* For Binance → Coinbase (USDC): Prefer Solana, Polygon, or Base → <$0.10 fee, <5 min
	* Adds safety check: Minimum transfer size $500+ (to avoid dust/minimums; simulate net cost (fee + slippage) before transferring).
	* One job: Keep average transfer cost per rebalance <$1 (achievable on above networks), ensuring operational costs stay <0.5% of capital annually.
8. [[Q-Bot]]
	* SIMPLE Cross Exchange Arbitrage (80% of Qbot capital) (10s cycles)
	* TRIANGULAR Arbitrage (20% of Qbot Capital) (30s cycles)
	* BOTH:
	    * Run in tight continuous loop (every 10-30s, independent paralled threads).
	    * Subscribes to fast WS data.
	    * Both take advantage of USDT and USDC prices
	    * Uses auction_context & order_executor logic
	    * Scans for arb opportunities (cross/triangular diffs).
	    * Calculates net profit (fees/slippage/transfers).
	    * Executes trades if profitable (limit/market mix, volume profiles, latency).
	    * Always active; uses its allocated capital share.
	    * One job: full arb cycle (scan + execute).
9. [MARKET SCANNER]
	* Compares price and order books to daily candle OHLC
	* Uses market_context logic (CVD, Wykoff, Wale Activity, VolProf)
	* Tells (Qbot when to be aggressive and when to be careful)
	* One job: watch for danger or opportunity in price swings.
10. [[A-Bot]]
	* Waits idle until [SIGNAL RECEIVER] gives a buy or sell signal.
	* On buy: uses its fuel share to buy the coin on the best exchange and stake it.
	* On sell: sells the coin on the best exchange.
	* If >3 slot is empty, automatically buy the highest-yield stakable coin, (seat warmer).
	* If <2 slot is empty automatically sell the “seat warmer” FIFO..
	* One job: handle the 6 long positions and staking when told.
11. [[G-Bot]]
	* Activates only in GOLD mode (told by Mode Manager).
	* Uses its fuel share to buy PAXG on the best exchange/pair.
	* IF {{MANUAL SWEEP}} is PRESSED during BTC MODE (max frequency, x1 a month), moves 15% 	of total profits to cold wallet in PAXG.
	* On mode flip to BTC, sells 85% of PAXG to free up fuel
	* keeps remaining 15% on a cold wallet
	* every cycle keeps 15%
	* One job: manage gold accumulation and sweeps.

### Current Refactor Goal (Hexagonal Architecture)
***TASK***
- CHECK if pure functions are still scattered or reiterated multiple times across multiple files.
- any function usually needs to SCAN/FETCH - CALCULATE - ANALYZE - EXECUTE

**Rules**:
- Never change the strategy, settings, or existing nomenclature.
- Use Decimal everywhere for money calculations.

