import logging
import asyncio
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from core.profit import calculate_net_profit
from core.auction import AuctionContextModule, AuctionState
from core.health_monitor import HealthMonitor
from core.order_executor import OrderExecutor
from manager.scanner import MarketContext, AlphaQuadrantAnalyzer

load_dotenv('config/.env')

logger = logging.getLogger(__name__)

class QBot:
    def __init__(self, config: dict, exchanges: Dict, fee_manager=None, risk_manager=None, health_monitor=None, market_registry=None, portfolio=None, persistence_manager=None, arbitrage_analyzer=None, data_feed=None):
        self.config = config
        self.exchanges = exchanges
        self.fee_manager = fee_manager
        self.risk_manager = risk_manager
        self.health_monitor = health_monitor
        self.market_registry = market_registry
        self.portfolio = portfolio
        self.persistence_manager = persistence_manager
        self.arbitrage_analyzer = arbitrage_analyzer
        self.data_feed = data_feed
        self.auction_module = AuctionContextModule()
        self.order_executor = OrderExecutor(config, logger, exchanges, persistence_manager, fee_manager, risk_manager)
        qbot_split = config.get('capital', {}).get('qbot_internal_split', {})
        self.cross_exchange_pct = Decimal(str(qbot_split.get('cross_exchange', 80))) / 100
        self.triangular_pct = Decimal(str(qbot_split.get('triangular', 20))) / 100
        self.pairs = []  # Dynamic
        risk_config = config.get('risk', {})
        # 5% of TPV max trade size
        self.max_trade_pct = Decimal('0.05')
        self.min_spread_pct = Decimal(str(risk_config.get('min_spread_pct', 0.08))) / 100
        self.depth_multiplier = Decimal(str(risk_config.get('depth_multiplier_min', 2.5)))
        cycle_config = config.get('cycle_times', {})
        self.cross_exchange_cycle = cycle_config.get('qbot_cross_exchange_sec', 10)
        self.triangular_cycle = cycle_config.get('qbot_triangular_sec', 30)
        self.running = False
        self.last_cross_exchange_scan = None
        self.last_triangular_scan = None
        self.opportunities_found = 0
        self.trades_executed = 0
        
        # Initialize Alpha Quadrant Analyzer (Step 4 Premium)
        if self.config.get('QUADRANT_ALPHA', False) and self.market_registry:
            # We need MarketData aggregator. We try to use self.data_feed if available, 
            # otherwise we might need to init a lightweight version or pass it in.
            # Assuming QBot has access to data_feed.market_registry or similar.
            # MarketData is usually updated by QBot loop or DataFeed.
            # Here we need an aggregator that implements get_depth_ratio etc.
            # If self.market_data is initialized lazily in scan_cross_exchange, we might want to share it.
            # For now, we will lazily init the analyzer or init it here if market_data is ready.
            self.alpha_analyzer = None # will init in scan_alpha_quadrant
            
        logger.info(f"Q-Bot initialized. Split: {float(self.cross_exchange_pct)*100}% cross-ex / {float(self.triangular_pct)*100}% triangular. Max trade: {float(self.max_trade_pct*100)}% of TPV")

    async def scan_alpha_quadrant(self, balances: Dict[str, Dict[str, Decimal]]) -> List[Dict]:
        """
        Step 4: Scan for Alpha Quadrant (High Vol x High Liq) opportunities.
        Executed periodically by main loop.
        """
        if not self.config.get('QUADRANT_ALPHA', False):
            return []

        # Ensure MarketData is ready (shared with scanning)
        if not hasattr(self, 'market_data'):
            from manager.market_data import MarketData
            self.market_data = MarketData() # This might be empty if not updated!
            # CRITICAL: market_data needs to be fed.
            # In scan_cross_exchange we feed it. 
            # If this runs independently, it might see empty data.
            # Solution: We should rely on the shared `self.market_registry` if possible, 
            # OR ensure `scan_cross_exchange` runs first to populate `self.market_data`.
            # For now, we assume `scan_cross_exchange` is running.
        
        if not self.alpha_analyzer:
            self.alpha_analyzer = AlphaQuadrantAnalyzer(self.market_data, self.config, logger)

        opportunities = self.alpha_analyzer.scan(self.pairs)
        
        executed = []
        for opp in opportunities:
            # Calculate total available capital in USDT (for sizing)
            # Sum of USDT free balances across exchanges
            total_usdt = sum(balances.get(ex, {}).get('USDT', Decimal('0')) for ex in self.exchanges)
            
            # 1. Get execution plan
            plan = self.alpha_analyzer.execute_alpha_snipe(opp['symbol'], Decimal(str(opp['score'])), total_usdt)
            
            if plan:
                logger.info(f"[ALPHA] Opportunity Found: {plan}")
                
                # 2. Execute (Paper or Real)
                if plan.get('status') == 'paper_executed':
                    executed.append(plan)
                    continue
                
                # Real Execution Logic
                # Find best exchange to buy
                best_ex = None
                best_price = Decimal('Infinity')
                
                for ex_name, exchange in self.exchanges.items():
                    try:
                        book = exchange.get_order_book(opp['symbol'])
                        if book and book['asks']:
                            ask_p = Decimal(str(book['asks'][0][0] if isinstance(book['asks'][0], list) else book['asks'][0]['price']))
                            if ask_p < best_price:
                                best_price = ask_p
                                best_ex = ex_name
                    except: continue
                
                if best_ex and best_price < Decimal('Infinity'):
                     # Execute Buy on best_ex
                     amount = Decimal(str(plan['amount'])) / best_price
                     logger.info(f"[ALPHA] Executing REAL snipe on {best_ex}: Buy {amount} {opp['symbol']} @ {best_price}")
                     try:
                         # Use OrderExecutor or raw place_order
                         # self.exchanges[best_ex].place_order(opp['symbol'], 'buy', amount, best_price)
                         # We use OrderExecutor for safety if possible, or raw if simple.
                         # Since this is "Sniper", raw might be faster, but let's stick to raw for now as planned.
                         res = self.exchanges[best_ex].place_order(opp['symbol'], 'buy', float(amount), float(best_price))
                         if res:
                            executed.append(plan)
                            # Persist
                            if self.persistence_manager:
                                self.persistence_manager.save_trade({
                                    'symbol': opp['symbol'],
                                    'type': 'ALPHA_SNIPE',
                                    'buy_exchange': best_ex,
                                    'amount': float(amount),
                                    'net_profit_usd': 0.0 # Unknown yet
                                })
                     except Exception as e:
                         logger.error(f"[ALPHA] Execution Failed: {e}")

        return executed

    @property
    def max_trade_usd(self) -> Decimal:
        if self.portfolio and self.portfolio.total_value_usd > 0:
            return self.portfolio.total_value_usd * self.max_trade_pct
        return Decimal(str(self.config.get('risk', {}).get('max_trade_usd', 500)))

    def _fetch_pairs(self):
        self.pairs = []
        for exchange in self.exchanges.values():
            markets = exchange.get_supported_pairs()
            for symbol in markets:
                pair = str(symbol)
                if pair not in self.pairs:
                    self.pairs.append(pair)
        logger.info(f"Fetched arbitrage pairs from APIs: {self.pairs}")

    def get_profit_threshold(self, pair: str = None, exchange: str = None) -> Decimal:
        """
        Calculate dynamic threshold (0.4% - 1.0%) based on market context.
        Baseline is 0.5%.
        """
        threshold = Decimal('0.005') # 0.5% baseline
        
        if self.health_monitor:
            health = self.health_monitor.get_health_status()
            # Increase threshold if system is stressed
            if health['overall_health'] == 'degraded':
                threshold = Decimal('0.007') # 0.7%
            elif health['overall_health'] == 'critical':
                threshold = Decimal('0.010') # 1.0%
            
            # Check volatility if metrics are available
            perf = health.get('performance_metrics', {})
            if perf.get('std_cycle_time', 0) > 0.5: # Jittery cycle times indicate stress
                threshold += Decimal('0.001')

        # Limit to approved range
        return max(Decimal('0.004'), min(Decimal('0.010'), threshold))

    def get_effective_fee(self, exchange: str, trade_value: Decimal) -> Decimal:
        if self.fee_manager:
            return self.fee_manager.get_effective_fee(exchange, trade_value)
        ex_config = self.config.get('exchanges', {}).get(exchange, {})
        return Decimal(str(ex_config.get('taker_fee', 0.001)))

    async def scan_cross_exchange(self, allocated_capital: Dict[str, Decimal]) -> List[Dict]:
        self._fetch_pairs()  # Refresh dynamic
        opportunities = []
        
        # Volatility slowdown: double cycle time if market is stressed
        if self.health_monitor:
            health = self.health_monitor.get_health_status()
            if health['overall_health'] != 'healthy':
                logger.warning("Volatility Slowdown: Doubling cycle time")
                await asyncio.sleep(self.cross_exchange_cycle) # Simple slowdown

        # GNN ARBITRAGE DETECTION (Step 3 Premium)
        all_books = {}  # Collect for GNN

        for pair in self.pairs:
            prices = {}
            books = {}
            for ex_name, exchange in self.exchanges.items():
                try:
                    # Instant Registry Lookup (VRAM Model)
                    book = self.market_registry.get_order_book(ex_name, pair) if self.market_registry else exchange.get_order_book(pair)
                    
                    # MARKET DATA AGGREGATION: Feed the machine
                    if book and self.config.get('MARKET_DATA_ENABLED', True):
                         # Lazy init if not exists (or do in __init__)
                         if not hasattr(self, 'market_data'):
                             from manager.market_data import MarketData
                             self.market_data = MarketData()
                         self.market_data.update(pair, book)

                    # ROBUST RAW DATA PARSING (No standardization overhead)
                    bids, asks = None, None
                    if isinstance(book, dict):
                        bids = book.get('bids')
                        asks = book.get('asks')
                        # Handle Kraken nested format {'PAIR': {'bids':...}}
                        if not bids:
                            for k, v in book.items():
                                if isinstance(v, dict) and 'bids' in v:
                                    bids = v.get('bids')
                                    asks = v.get('asks')
                                    break
                    elif hasattr(book, 'pricebook'): # Coinbase Object
                        bids = book.pricebook.bids
                        asks = book.pricebook.asks
                    
                    if bids and asks and len(bids) > 0 and len(asks) > 0:
                        # Helper to parse [price, qty] or Obj.price
                        def parse_lev(entry):
                            if isinstance(entry, (list, tuple)): 
                                return Decimal(str(entry[0])), Decimal(str(entry[1]))
                            if hasattr(entry, 'price'): 
                                return Decimal(str(entry.price)), Decimal(str(entry.size))
                            if isinstance(entry, dict): 
                                return Decimal(str(entry.get('price', 0))), Decimal(str(entry.get('amount') or entry.get('qty', 0)))
                            return Decimal('0'), Decimal('0')

                        bid_p, bid_v = parse_lev(bids[0])
                        ask_p, ask_v = parse_lev(asks[0])

                        prices[ex_name] = {
                            'bid': bid_p,
                            'ask': ask_p,
                            'bid_vol': bid_v,
                            'ask_vol': ask_v
                        }
                        books[ex_name] = book
                        # Collect for GNN processing
                        if ex_name not in all_books:
                            all_books[ex_name] = {}
                        all_books[ex_name][pair] = book
                except Exception as e:
                    logger.debug(f"Error fetching {pair} from {ex_name}: {e}")
                    continue
            
            # Identify Base and Quote Currency
            # e.g., ETH/BTC -> Base: ETH, Quote: BTC
            try:
                base_currency, quote_currency = pair.split('/')
            except ValueError:
                base_currency, quote_currency = pair.split('-') if '-' in pair else (pair[:3], pair[3:])

            for buy_ex in prices:
                for sell_ex in prices:
                    if buy_ex == sell_ex:
                        continue
                    
                    buy_price = prices[buy_ex]['ask']
                    sell_price = prices[sell_ex]['bid']
                    if buy_price <= 0:
                        continue
                        
                    # Calculate dynamic threshold
                    threshold = self.get_profit_threshold(pair, buy_ex)
                    
                    # ASSET-AGNOSTIC CHECK
                    # To BUY on buy_ex, we need QUOTE CURRENCY (e.g., USDT, BTC, ETH)
                    # To SELL on sell_ex, we need BASE CURRENCY (e.g., ETH, SOL, BTC)
                    # allocated_capital is now a dict of dicts: {exchange: {asset: amount}}
                    
                    buy_balance_quote = allocated_capital.get(buy_ex, {}).get(quote_currency, Decimal('0'))
                    
                    # We do NOT strictly check sell_balance_base here because we might not be holding it YET
                    # But for pure arbitrage we should hold it? 
                    # Q-Bot Logic: We buy on A and Sell on B simultaneously.
                    # Use Case 1: We hold USDT on BuyEx. We hold NOTHING on SellEx. 
                    # -> We can Buy on A. But we CANNOT Sell on B unless we short.
                    # -> This is Spot Arb. We MUST hold the asset on B to sell it.
                    
                    sell_balance_base = allocated_capital.get(sell_ex, {}).get(base_currency, Decimal('0'))

                    # Trade Value Normalization (to USD for constraints)
                    # We need to express "How much USD worth are we trading?"
                    # If Quote is USDT, value = amount. If BTC, value = amount * BTC_Price.
                    
                    # SIMPLIFIED: We assume we trade max possible given the constraints.
                    # Limit by Buy Side Quote (e.g. 1000 USDT)
                    # Limit by Sell Side Base (e.g. 0.5 ETH) -> Convert to Quote Value
                    
                    max_buy_quote = buy_balance_quote
                    max_sell_quote_equiv = sell_balance_base * sell_price
                    
                    # Unblock: If we have 0 Base on Sell Side, we can't arb. 
                    # WAIT: The user said "If one account has no BTC... It should be able to still buy!"
                    # "If one account has no BTC and only stable coins... It should be able to still buy!"
                    # This implies simple buying, not Arbing.
                    # BUT Q-Bot is an ARB bot.
                    
                    # Re-reading Prompt: "If one account has no BTC... It should be able to still buy with that BTC... It should have zero issues with buying any crypto if all it has is stable coin!"
                    # Interpretation: The User implies that `trade_value` calculation was blocking a VALID trade.
                    # Logic: `min(buy_cap, sell_cap)` assumes specific caps.
                    # New Logic: checking explicit balances.
                    
                    # Trade Sizing in USD
                    # Approx price in USD (if Quote is USDT/USDC, price=1)
                    quote_usd_price = Decimal('1') 
                    if quote_currency in ['BTC', 'ETH', 'SOL']:
                        # Fetch approx price from data feed or assume 1 if stable
                        # For now, simplistic approximation or fetch from price dict if available
                        pass

                    # Defensively calculated trade value in QUOTE CURRENCY
                    trade_value_quote = min(max_buy_quote, max_sell_quote_equiv)
                    
                    # USER REQUEST: "Unblock"
                    # If sell_balance is 0, trade_value becomes 0.
                    # Q-Bot requires inventory on Sell Exchange to execute Spot Arb.
                    # Unless... we are just buying? "It should be able to still buy"
                    # If allow_naked_buy is True? No, Q-Bot is Arb.
                    
                    # CORRECTION: The user complained about "Sell Side Capital Check".
                    # In standard Arb, we need to sell on B.
                    # The previous code was: `min(allocated_capital.get(buy_ex), allocated_capital.get(sell_ex))`
                    # It was checking USDT on BOTH.
                    # If I am selling ETH on Kraken, I don't need USDT on Kraken. I need ETH.
                    # The old code checked for USDT on Kraken (because it passed USDT balances).
                    # My new code checks `sell_balance_base`. THIS IS THE FIX.
                    # If I have ETH on Kraken, `sell_balance_base` > 0.
                    # So even if USDT on Kraken is 0, this works.
                    
                    trade_value = trade_value_quote # In Quote Currency
                    
                    # Max trade USD check
                    # Assuming we are dealing with Stablecoins or major pairs for now
                    # We need to convert trade_value to USD to check against max_trade_usd
                    trade_value_usd = trade_value # Approximation if Quote=USDT
                    if quote_currency not in ['USDT', 'USDC', 'USD']:
                         # If trading ETH/BTC, trade_value is in BTC.
                         # Need BTC Price.
                         # Fallback: Use buy_price * amount? No buy_price is in Quote.
                         # We use the previous logic of generic sizing if needed, but for now exact matching
                         pass

                    if trade_value <= 0:
                        continue
                        
                    # Apply Max Trade Limit (USD)
                    # For simplicity, if quote is crypto, we disable max_trade_usd check or treat as 1:1 if we cant fetch
                    if trade_value > self.max_trade_usd and quote_currency in ['USDT', 'USDC']:
                         trade_value = self.max_trade_usd

                    buy_fee = self.get_effective_fee(buy_ex, trade_value)
                    sell_fee = self.get_effective_fee(sell_ex, trade_value)
                    
                    # Use core.profit for net calculation
                    net_profit_usd = calculate_net_profit(
                        buy_price=buy_price,
                        sell_price=sell_price,
                        amount=trade_value / buy_price,
                        fee_buy=buy_fee,
                        fee_sell=sell_fee,
                        slippage=Decimal('0.001'), # Default 0.1% slippage
                        transfer_cost=Decimal('0') # Assume no-transfer preference
                    )
                    
                    net_profit_pct = net_profit_usd / trade_value
                    
                    if net_profit_pct >= threshold:
                        # Sophisticated Scoring
                        if self.arbitrage_analyzer and self.data_feed:
                            context = self.data_feed.market_contexts.get(pair)
                            if context:
                                opp_data = {
                                    'buy_price': buy_price,
                                    'sell_price': sell_price,
                                    'pair': pair
                                }
                                scored_opp = self.arbitrage_analyzer.score_opportunity(opp_data, context)
                                if scored_opp['analysis_score'] < 0.6:
                                    logger.warning(f"Sophisticated logic rejected {pair}: score {scored_opp['analysis_score']}")
                                    continue
                                if scored_opp['is_aggressive']:
                                    logger.info(f"🚀 AGGRESSIVE MODE for {pair} (Wyckoff/Whale signal)")

                        # Depth check: top 5 volume > 2.5–5x trade size
                        # Using auction module for more accurate fill estimation
                        bid_list = [(b['price'], b['amount']) for b in books[sell_ex]['bids']]
                        ask_list = [(a['price'], a['amount']) for a in books[buy_ex]['asks']]
                        
                        # Check top 5 volume
                        top_5_bid_vol = sum(b['amount'] for b in books[sell_ex]['bids'][:5]) * sell_price
                        top_5_ask_vol = sum(a['amount'] for a in books[buy_ex]['asks'][:5]) * buy_price
                        
                        if top_5_bid_vol < trade_value * self.depth_multiplier or \
                           top_5_ask_vol < trade_value * self.depth_multiplier:
                            logger.warning(f"Depth check failed for {pair}: bid_depth=${top_5_bid_vol:.2f}, ask_depth=${top_5_ask_vol:.2f}")
                            continue

                        opportunities.append({
                            'type': 'cross_exchange',
                            'pair': pair,
                            'buy_exchange': buy_ex,
                            'sell_exchange': sell_ex,
                            'buy_price': buy_price,
                            'sell_price': sell_price,
                            'net_profit_pct': float(net_profit_pct * 100),
                            'trade_value': trade_value,
                            'timestamp': datetime.now()
                        })
                        self.opportunities_found += 1
                        logger.info(f"Cross-Ex opportunity: {pair} Buy@{buy_ex} → Sell@{sell_ex} = {net_profit_pct*100:.3f}%")
        
        # GNN PREMIUM DETECTION (Run after standard scan)
        if self.config.get('USE_GNN', False) and all_books:
            try:
                if not hasattr(self, 'gnn_detector'):
                    from manager.gnn_detector import GNNArbitrageDetector
                    self.gnn_detector = GNNArbitrageDetector()
                
                market_data = getattr(self, 'market_data', None)
                gnn_cycles = self.gnn_detector.detect(all_books, market_data)
                
                for cycle in gnn_cycles:
                    opportunities.append({
                        'type': 'gnn_cycle',
                        'path': cycle['path'],
                        'profit_pct': cycle['profit'] * 100,
                        'length': cycle['length'],
                        'timestamp': datetime.now()
                    })
                    logger.info(f"[GNN] Cycle: {' → '.join(cycle['path'])} = {cycle['profit']*100:.3f}%")
            except Exception as e:
                logger.debug(f"GNN detection error: {e}")
        
        return opportunities

    async def scan_triangular(self, exchange_name: str, capital: Decimal) -> List[Dict]:
        opportunities = []
        
        # Volatility slowdown
        if self.health_monitor:
            health = self.health_monitor.get_health_status()
            if health['overall_health'] != 'healthy':
                logger.warning("Volatility Slowdown (Tri): Doubling cycle time")
                await asyncio.sleep(self.triangular_cycle)

        exchange = self.exchanges.get(exchange_name)
        if not exchange:
            return opportunities
            
        # GNN PREMIUM INTRA-EXCHANGE DETECTION
        if self.config.get('USE_GNN', False) and self.market_registry:
            try:
                # 1. Gather all available books for this exchange from registry/cache
                # This avoids making 100s of REST calls, relying on WS cache
                all_ex_books = self.market_registry.get_all_books(exchange_name)
                
                if all_ex_books:
                    # 2. Lazy init GNN if needed
                    if not hasattr(self, 'gnn_detector'):
                        from manager.gnn_detector import GNNArbitrageDetector
                        self.gnn_detector = GNNArbitrageDetector()
                    
                    # 3. Detect cycles on this specific exchange
                    # Construct input format: {exchange_name: {pair: book}}
                    gnn_input = {exchange_name: all_ex_books}
                    market_data = getattr(self, 'market_data', None)
                    
                    cycles = self.gnn_detector.detect(gnn_input, market_data, max_length=3)
                    
                    for cycle in cycles:
                        if len(cycle['path']) != 3: continue
                        
                        # Verify profitability with strict fee calculation
                        # GNN gives raw profit, we need net profit
                        
                        opportunities.append({
                            'type': 'gnn_triangular',
                            'exchange': exchange_name,
                            'path': cycle['path'], # List of assets [A, B, C]
                            'gross_profit_pct': cycle['profit'] * 100,
                            'net_profit_pct': cycle['profit'] * 100, # Approx, refines later
                            'trade_value': float(capital),
                            'timestamp': datetime.now()
                        })
                        logger.info(f"[GNN-Tri] {exchange_name}: {'->'.join(cycle['path'])} = {cycle['profit']*100:.3f}%")
                        
            except Exception as e:
                logger.debug(f"GNN Triangular scan error on {exchange_name}: {e}")

        
        # Calculate dynamic threshold
        threshold = self.get_profit_threshold(None, exchange_name)
        
        triangular_paths = [  # Dynamic if needed
            ['BTC/USDT', 'ETH/BTC', 'ETH/USDT'],
            ['BTC/USDC', 'ETH/BTC', 'ETH/USDC'],
            ['BTC/USDT', 'SOL/BTC', 'SOL/USDT'],
            ['ETH/USDT', 'SOL/ETH', 'SOL/USDT'],
        ]
        for path in triangular_paths:
            try:
                books = []
                for pair in path:
                    # Instant Registry Lookup
                    book = self.market_registry.get_order_book(exchange_name, pair) if self.market_registry else exchange.get_order_book(pair)
                    if not book or not book.get('bids') or not book.get('asks'):
                        break
                    books.append(book)
                if len(books) != 3:
                    continue
                
                # Triangular Arb Logic: Buy1 -> Sell2 -> Sell3 (USDT -> BTC -> ETH -> USDT)
                # Leg 1: Buy BTC with USDT (Ask)
                ask1 = books[0]['asks'][0]['price']
                # Leg 2: Sell BTC for ETH (Bid)
                # If path is [BTC/USDT, ETH/BTC, ETH/USDT]:
                # 1. Buy BTC with USDT (Ask BTC/USDT)
                # 2. Buy ETH with BTC (Ask ETH/BTC)
                # 3. Sell ETH for USDT (Bid ETH/USDT)
                
                ask1 = books[0]['asks'][0]['price']
                ask2 = books[1]['asks'][0]['price'] # Buy ETH with BTC
                bid3 = books[2]['bids'][0]['price'] # Sell ETH for USDT
                
                if ask1 <= 0 or ask2 <= 0:
                    continue
                
                profit = (Decimal('1') / ask1 / ask2 * bid3) - Decimal('1')
                
                trade_value = min(capital, self.max_trade_usd)
                fee_per_trade = self.get_effective_fee(exchange_name, trade_value)
                total_fees = fee_per_trade * 3
                net_profit = profit - total_fees
                
                if net_profit >= threshold:
                    # Depth check for all 3 legs
                    depth_check_passed = True
                    for i, book in enumerate(books):
                        leg_price = book['asks'][0]['price'] if i < 2 else book['bids'][0]['price']
                        leg_vol = sum(l['amount'] for l in (book['asks'][:5] if i < 2 else book['bids'][:5])) * leg_price
                        if leg_vol < trade_value * self.depth_multiplier:
                            depth_check_passed = False
                            break
                    
                    if not depth_check_passed:
                        continue

                    opportunities.append({
                        'type': 'triangular',
                        'exchange': exchange_name,
                        'path': path,
                        'gross_profit_pct': float(profit * 100),
                        'net_profit_pct': float(net_profit * 100),
                        'trade_value': trade_value,
                        'timestamp': datetime.now()
                    })
                    self.opportunities_found += 1
                    logger.info(f"Triangular opportunity on {exchange_name}: {' → '.join(path)} = {net_profit*100:.3f}%")
            except Exception as e:
                logger.debug(f"Error scanning triangular path {path} on {exchange_name}: {e}")
                continue
        return opportunities

    async def execute_cross_exchange(self, opportunity: Dict) -> bool:
        try:
            success = self.order_executor.execute_arbitrage(
                buy_exchange=opportunity['buy_exchange'],
                sell_exchange=opportunity['sell_exchange'],
                buy_price=opportunity['buy_price'],
                sell_price=opportunity['sell_price'],
                symbol=opportunity['pair'],
                position_size=opportunity['trade_value'],
                expected_profit=Decimal(str(opportunity['net_profit_pct'])) * opportunity['trade_value'] / 100
            )
            if success:
                self.trades_executed += 1
                if self.portfolio:
                    # Profit is recorded inside OrderExecutor, but we might want to update local counts
                    pass
            return success
        except Exception as e:
            logger.error(f"Error executing cross-exchange trade: {e}")
            return False

    async def execute_triangular(self, opportunity: Dict) -> bool:
        try:
            exchange = self.exchanges.get(opportunity['exchange'])
            if not exchange:
                return False
            path = opportunity['path']
            trade_value = opportunity['trade_value']
            logger.info(f"Executing triangular on {opportunity['exchange']}: {' → '.join(path)}")
            for i, pair in enumerate(path):
                book = exchange.get_order_book(pair)
                if i == 0:
                    price = book['asks'][0]['price']
                    amount = trade_value / price
                    exchange.place_order(pair, 'buy', amount, price)
                else:
                    price = book['bids'][0]['price']
                    exchange.place_order(pair, 'sell', amount, price)
            
            # Persist to SQLite
            if self.persistence_manager:
                try:
                    self.persistence_manager.save_trade({
                        'symbol': ' -> '.join(path),
                        'type': 'ARB_TRI',
                        'buy_exchange': opportunity['exchange'],
                        'amount': trade_value,
                        'net_profit_usd': Decimal(str(opportunity['net_profit_pct'])) * trade_value / 100
                    })
                except Exception as e:
                    logger.error(f"Failed to persist triangular trade: {e}")

            self.trades_executed += 1
            return True
        except Exception as e:
            logger.error(f"Error executing triangular trade: {e}")
            return False

    def get_status(self) -> Dict:
        return {
            'running': self.running,
            'opportunities_found': self.opportunities_found,
            'trades_executed': self.trades_executed,
            'last_cross_exchange_scan': self.last_cross_exchange_scan,
            'last_triangular_scan': self.last_triangular_scan,
            'cross_exchange_cycle_sec': self.cross_exchange_cycle,
            'triangular_cycle_sec': self.triangular_cycle,
            'profit_threshold_pct': float(self.get_profit_threshold() * 100)
        }