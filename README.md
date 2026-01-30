## Agent Instructions

This file is mirrored across CLAUDE.md, AGENTS.md, and GEMINI.md so the same instructions load in any AI environment.

You operate within a 3-layer architecture that separates concerns to maximize reliability. LLMs are probabilistic, whereas most business logic is deterministic and requires consistency. This system fixes that mismatch.

### The 3-Layer Architecture

**Layer 1: Directive (What to do)**  
- Markdown SOPs in `directives/` (or embedded here).  
- Define goals, inputs, tools/scripts to use, outputs, edge cases.  
- Natural language instructions, like you'd give a mid-level employee.

**Layer 2: Orchestration (Decision making)**  
- This is you (the AI). Your job: intelligent routing.  
- Read directives, call execution tools/scripts in the right order, handle errors, ask for clarification, update directives with learnings.  
- You're the glue between intent and execution. E.g., don't try scraping websites yourself—read `directives/scrape_website.md` and run `execution/scrape_single_site.py`.  
- Focus on decision-making; push complexity to deterministic code.

**Layer 3: Execution (Doing the work)**  
- Deterministic Python scripts in `execution/` (or equivalent).  
- Environment variables, API tokens, etc. stored in `.env`.  
- Handle API calls, data processing, file operations, database interactions.  
- Reliable, testable, fast. Use scripts instead of manual work. Commented well.

**Why this works:** If you do everything yourself, errors compound. 90% accuracy per step = 59% success over 5 steps. The solution is push complexity into deterministic code. That way you just focus on decision-making.

### Operating Principles

1. **Check for tools first**  
   Before writing a script, check existing ones in `execution/` per your directive. Only create new scripts if none exist.

2. **Self-anneal when things break**  
   - Read error message and stack trace.  
   - Fix the script and test it again (unless it uses paid tokens/credits/etc.—in which case check with user first).

Now apply this architecture to the project below.

## Project Goal & Hexagonal Refactor Instructions

This is a cryptocurrency arbitrage and hedging bot designed for a ~$10,000 budget in January 2026.

### Core Strategy (100% to be preserved)

The system operates in two primary modes based on a custom TradingView signal:

Macro Signal:
	* Fired (BUY BTC/SELL PAXG) on Nov 2023 = BTC Mode
	* Fired another signal on Nov 2025 (SELL BTC/BUY PAXG) = GOLD Mode.
Capital Allocation:
	* BTC Mode: 85% → [Q-Bot], 15% → [A-Bot], 0% → [G-Bot]
	* GOLD Mode: 15% → [Q-Bot], 0% → [A-Bot], 85% → [G-Bot]
System Components
1. [SIGNAL RECEIVER]
	* Listens for TradingView alerts (Macro Signal (mode flip) AND [A-Bot] (buy/sell) signals.
	* When something arrives, it immediately tells the Mode Manager or [A-Bot] when to buy/sell not what to do.
	* One job: Listens for TradingView alerts and passes them on. No polling, no timing.
2. [MODE MANAGER]
	* Holds the current state: BTC mode or GOLD mode.
	* Only changes when the [SIGNAL RECEIVER] tells it to (from Macro Signal).
	* Tells [MONEY MANAGER] which mode is active now.
	* Activates/deactivates bots according to BTC Mode or GOLD Mode
	* One job: remember the mode and announce/apply changes.
5. [MONEY MANAGER]
	* Tracks every penny.
	* Divides the capital for ALL.
	* Checks account balances periodically.
	* If [Q-Bot] arbitrage money becomes too uneven between accounts (>35% drift), signals [TRANSFER MANAGER] AND [CONVERSION MANAGER] to move USDT/USDC across accounts to even it out THE cheapest way.
	* Does not interrupt [Q-Bot]
    * During BOTTLENECK mode (when drift >35%) it checks which is quicker & more profitable option to rebalance accounts max transfers x2/week.
	* Tells [TRANSFER MANAGER] AND [CONVERSION MANAGER] what it needs to maintain the ideal portfolio proportions across accounts for arbitrage.
	* MULTIPLE JOBS: Divide and allocate capital. Prevent capital from accumulating in one account. 
6. [CONVERSION MANAGER]
	* It tries to keep drift <15% across exchanges by PROFITABLE INTRA-EXCHANGE triangular conversions (min profit >=1.5%).
	* Does not interrupt [Q-Bot]
	* One job: Reduces the amount needed to transfer by prioritizing internal triangular conversions (intra-exchange) over any cross-account transfers whenever possible to eliminate transfer fees entirely.
7. [TRANSFER MANAGER] 
	* Transfers USDT OR USDC (stable coins preferably over crypto) across accounts after calculating the speed of transfer and transfer fees across accounts
	* Receives transfer route from [CONVERSION MANAGER].
	* Does not interrupt [Q-Bot]
	* Always queries real-time network fees & times, at execution time and select the cheapest + fastest shared network between sender/receiver
	* Kraken <-> Binance.US can use USDT/USDC
    * Coinbase <-> Binance.US/KRAKEN use USDC ONLY!
    * ADDRESSES & networks:
      ##### BINANCE.US Wallets:
		- Network_SOL: 6nVkZ9DhUGpCSikwmwykjZkPCJkQEASVKKnrEScj3Ya8
          - deposit: USDT, USDC, SOL
        - Network_AVAX C-Chain: 0x9433ef65333256178a317bdefb8c18ad49b22350
          - deposit: USDT, USDC
        - Network_TRON (TRC20): THiAU5ReTWR9TBWVTv1WRKBY7j9qeZXFkw
          - deposit: USDT
      ##### KRAKEN Wallets: 
		- Network_SOL: FnFSRzQDSa1kfFKABS6onFid1yncwYC6TqKcCXe2bcQa
          - deposit : USDC, USDT, SOL
		- Network_AVAX C-Chain: 0x18791c1Ec171169B4E599A01D280a325500f1BB5
          - deposit: USDC, USDT
		- Network_Sui: 0x29d57083b1b274d6e78155c147f87a9964b8a9e0e28b890ec10a984447e35eab
          - deposit: USDC, SUI
		- Network_Algo: SMN5HNKR45Z6GB546A5KRI2AGODAYKSPMXLGL5PB5SFY6URD4MANLLAPKI
          - deposit: USDC
		- Network_TRON (TRC20): TLEvYy9aYUztMYqxvXcLshEdvqWwNFysMK
          - deposit: USDT
      ##### Coinbase USDC ONLY Wallets:
		- Network_SOL: rfXgbu6jQVgEThszwPBvCgHPq2LX59m4qZSLbneqczw
		- Network_AVAX C-Chain: 0x27FA5C63e7f7c2D07b349A8F44cc29870A32f8C6
		- Network_Sui: 0xc8cb27799a08da6f64e77f1267d3330fb5e01b13d6cbad1914e81ce069dc4ed6
		- Network_Algo: XFDI7INMVW32QUKO4QRBHNOIGSNA5AOX2MVWP5DHH3PUXX4JOCPWBF46AU
      ##### Coinbase Alt Wallets:
        - Network_SOL_2: Ch2d4gvee8jnJ384xacj4bsp3YWKAG9yMDS2u2MeWmcw
          - deposit: SOL 
        - Network_Sui_2: 0xf36f79b4353442fe95b5ddeaa2dafeada617d67b598ea1cf0d3d41a3153e5e61
          - deposit: SUI
	* Adds safety check: Minimum transfer size $500+ (to avoid dust/minimums; simulate net cost (fee + slippage) before transferring).
	* One job: Keep average transfer cost per rebalance <$1 (achievable on above networks), ensuring operational costs stay <0.5% of capital annually.
8. [Q-Bot]
	* SIMPLE Cross Exchange Arbitrage (80% of [Q-Bot] capital) (10s cycles)
      * [BTC/USD/USDT/USDC]
      * [ETH/USD/USDT/USDC]
      * [SOL/USD/USDT/USDC]
	* TRIANGULAR Cross Exchange Arbitrage (20% of [Q-Bot] Capital) (30s cycles)
      * [X <-> Y <-> USD/USDT/USDC] 
      * [X <-> USD/USDT/USDC <-> Y]
      * [USD/USDT/USDC <-> X <-> Y]
      *  X or Y = BTC/ETH/SOL
	* BOTH:
	    * Run in tight continuous loops (independent parallel threads).
	    * Subscribes to fast WS data.
	    * Both take advantage of USDT and USDC prices
	    * Uses auction_context & order_executor logic
	    * Scans for arb opportunities (cross/triangular diffs).
	    * Calculates net profit (fees/slippage/transfers).
	    * Executes trades if profitable (limit/market mix, volume profiles, latency).
	    * Always active; uses its allocated capital share.
	    * One job: full arb cycle = x3(simple) + x1(triangular).
10. [A-Bot]
	* Waits idle until [SIGNAL RECEIVER] gives a buy or sell signal.
	* On buy: uses its allocated share to buy the coin on the best exchange and stake it.
	* On sell: sells the coin on the best exchange.
	* If >3 slot is empty, automatically buy the highest-yield stakable coin, (seat warmer).
	* If <2 slot is empty automatically sell the “seat warmer” FIFO..
	* One job: handle the 6 long positions and staking when told.
11. [G-Bot]
	* Activates only in GOLD mode.
	* Uses its allocated share to buy PAXG on the best exchange/pair.
	* IF [MANUAL SWEEP] is PRESSED during BTC MODE (max frequency, x1 a month), moves 15% of total profits to BASE wallet in PAXG.
	* On mode flip to BTC, sells 85% of PAXG to free up fuel
	* Keeps remaining 15% on BASE wallet
	* Every cycle keeps 15%
	* One job: manage gold accumulation and sweeps.
9. [MARKET SCANNER]
	* Compares price and order books to daily candle OHLC
	* Uses market_context logic (CVD, Wykoff, Wale Activity, VolProf)
	* Tells [Q-Bot] when to be aggressive and when to be careful
	* One job: watch for danger or opportunity in price swings.
12. [FEE MANAGER]
     * Fetches lowest combined buy/sell fees
     * Maintains a min dynamic BNB balance.
     * Tracks 'zero fee' allowances per month for each account
     * One job: monitor and manage fees

All other files are critical for proper strategy function. 

### Current Refactor Goal (Hexagonal Architecture)

Refactor to clean hexagonal/ports & adapters without changing strategy. Core/domain pure, adapters for exchanges, managers for orchestration.

Prioritized fixes: fix drift disabling Q-Bot (unacceptable—use bottleneck mode if needed).
#### STEP1 "ACCEPT IMBALANCE - PROFIT OVER PERFECTION!"
the bot does not trade because drift is set at 15%. Increase to 35%. 
At no point in time should [Q-Bot] be interrupted! 
If one account has no BTC and only stable coins or no stable coins and only BTC. 
It should be able to still buy with that BTC, ETH or SOL!
It should have zero issues with buying any crypto if all it has is stable coin!
the point is, transfers are only a last resort!

The refactor is currently incomplete, unorganized, but functional. However as you can see from the most recent logs, account drift is disabling function. This is unnacceptable, I made a bottleneck mode specifically to keep [Q-Bot] running despite drift being more than 15%!

Review the links attached, they have all the answers. I want to modify the three prompts below to address all the changes i want to make.

Review official docs:  
- https://github.com/coinbase/coinbase-advanced-py/  
- https://docs.kraken.com/api/docs/guides/global-intro  
- https://docs.binance.us/#introduction  

### Prioritized Implementation Tasks

##### STEP2 "VRAM IS GREAT - BUT WE STILL NEED TO AGGREGATE QUARTERLY MARKET DATA FOR BETTER CALCULATIONS"
***updates to do*** 
**Prompt 1: Add MarketData (Foundation – run this first)**  

You are a senior Python developer for crypto bots. Additions only: no modifications or removals to existing code. Preserve all fallbacks and safety.

Context:
- bot/Q.py: Main loop, WS order books cached (from adapters/data/ws.py), scan_triangular() calls manager/conversion.py detect_triangle().
- All symbols.
- Order books: dict[exchange][pair] = {'bids': list[[price, qty]], 'asks': list[[price, qty]]}.
- Use existing utils/logger.py for logging.

Task: Add thread-safe MarketData for rolling features from WS updates.
1. Create new file: manager/market_data.py
   - Class MarketData:
     - __init__: self.windows = defaultdict(lambda: deque(maxlen=60))  # 60 min if 1-min updates
     - update(symbol, book, mid_price=None): append mid_price = (best_bid + best_ask)/2, lock with threading.Lock
     - get_volatility(symbol): return std dev of deque prices if len>=10 else 0.0 (use statistics.stdev or numpy if imported)
     - get_book_imbalance(symbol, depth_pct=0.05): cum_bid_qty, cum_ask_qty at depth_pct from mid; return (cum_bid - cum_ask)/(cum_bid + cum_ask) if total>0 else 0
     - get_depth_ratio(symbol, depth_pct=0.05): cum_bid_qty / cum_ask_qty at depth_pct
     - get_market_means(): dict with 'imbalance_mean', 'depth_ratio_mean' averaged over all symbols with data
     - get_price_momentum(symbol): (current - deque[0])/deque[0] if len>=2 else 0
   - Thread-safe: use lock for updates/queries.
2. In bot/Q.py: Instantiate aggregator = MarketData() in QBot class.
   - Hook WS callback (adapters/data/ws.py or Q.py loop): after book update, aggregator.update(symbol, book, mid_price=...)
3. Add config: MARKET_DATA_ENABLED: true (default true) to config/settings.json or .env
4. Log aggregator updates/errors.

Output: Diffs only for manager/market_data.py (new), bot/Q.py, config files and any other files that need to be updated.
Implement precisely.


##### STEP 3 "PREMUIM [Q-Bot] & conversion.py EDITION - NEEDS TO BE APPLIED TO BOTH TRIANGULAR ARBITRAGES - Efficient Triangular Arbitrage Detection via Graph Neural Networks"
SEARCH ONLINE TO LEARN HOW TO BEST APPLY THIS TO OUR STRATEGY:
**Prompt 2: Add GNN Arbitrage Detection (Update 1 – after aggregator is in)**  
You are a senior Python developer for crypto bots. Additions only, no changes to existing logic.

Context:
- manager/market_data.py now provides get_volatility(), get_depth_ratio() etc.
- bot/Q.py: order books refreshed in main loop.
- manager/conversion.py: detect_triangle() uses itertools.permutations (legacy).
- core/profit.py for profit calc.

Task: Add optional GraphSAGE cycle detection.
1. Add to requirements.txt: torch torch-geometric networkx
2. New functions in manager/conversion.py (or new file if preferred):
   - build_market_graph(books, aggregator): nx.DiGraph()
     - Nodes: assets from monitored symbols
     - Edges: for each ex-pair in books: from base to quote, weight=-math.log(ask_price), features={'volume': sum top bids+asks qty, 'volatility': aggregator.get_volatility(base) or 0, 'fee': ex fee from config/wrappers, 'exchange': one-hot (use dict or np.array)}
   - gnn_spot_cycles(graph): 2-layer GraphSAGE (mean aggregator, ReLU), PyG Data from graph, inference → node embeddings. Use NetworkX simple_cycles on subgraph (high embedding similarity nodes). Score paths by potential profit or embedding dot. Return list of scored cycles.
3. In bot/Q.py main loop (after books refresh): if config.USE_GNN:
   - graph = build_market_graph(books, self.aggregator)
   - cycles = gnn_spot_cycles(graph)
   - For each cycle: calc profit via core/profit.py → feed to manager/scanner.py score_opportunity()
4. Fallback: if not USE_GNN or error: run legacy detect_triangle()
5. Add config.USE_GNN: false to config/settings.json
6. Log graph build, inference time, cycles found.

Output: Diffs for requirements.txt, manager/conversion.py, bot/Q.py, config files and any other files that need to be updated.
Implement step-by-step.

##### STEP 4 "PREMUIM [A-Bot] EDITION - QUADRANT ALPHA SNIPER"
SEARCH ONLINE TO LEARN HOW TO BEST APPLY THIS TO OUR STRATEGY:
**Prompt 3: Add Coin Quadrant Alpha Sniper (Update 2 – last)**
You are a senior Python developer for crypto bots. Additions only.

Context:
- manager/market_data.py: get_depth_ratio(), get_book_imbalance(), get_market_means(), get_price_momentum()
- manager/scanner.py: ArbitrageAnalyzer.score_opportunity()
- bot/Q.py: main loop, capital management.
- core/order_executor.py for execution.

Task: Add Quadrant Alpha Sniper (15% allocation, premium).
1. New class in manager/scanner.py: AlphaQuadrantAnalyzer
   - __init__: self.aggregator, self.threshold = config.ALPHA_THRESHOLD or 1.5
   - scan(): every 5-15 min (use threading.Timer or time check in Q.py)
     - For each symbol in monitored:
       - x = aggregator.get_depth_ratio(symbol, 0.05)  # bid/ask qty ratio at 5%
       - y = aggregator.get_book_imbalance(symbol, 0.05)  # proxy for whale delta
       - means = aggregator.get_market_means()
       - bonus = abs(aggregator.get_price_momentum(symbol))  # or 0
       - score = (x > means['depth_ratio_mean'] and y > means['imbalance_mean']) * (y * x * (1 + bonus))
     - If score > threshold: threading.Thread(target=self.execute_alpha_snipe, args=(symbol, score))
   - execute_alpha_snipe(symbol, score): amount = 0.15 * available_capital; check paper_mode; call core/order_executor buy/stake with hold rules; log
2. In bot/Q.py: If config.QUADRANT_ALPHA: start analyzer.scan() timer in __init__ or loop.
3. Extend scanner.score_opportunity(): add quadrant_score if QUADRANT_ALPHA true.
4. Config additions: QUADRANT_ALPHA: false, ALPHA_THRESHOLD: 1.5
5. Safety: separate capital check, log only, paper_mode blocks trades.

Output: Diffs for manager/scanner.py, bot/Q.py, config files.
One test: mock 3 symbols with books/prices (one top-right), verify score and trigger.
Implement precisely.
These are ~400-500 tokens each (JetBrains free tier handles fine; paid is safe). Paste sequentially, confirm diffs add only, commit to new branch (_premium_FIXED). If AI wanders, reply “Additions only, fix to match prompt exactly.” This should give you clean, accurate premium upgrades. Let me know the results after the first one!


**Rules**:
- Never change the strategy, settings, or existing nomenclature without approval and confirmation.
- Use Decimal everywhere for money calculations.

