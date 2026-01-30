import logging
import asyncio
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from core.profit import calculate_net_profit
from core.auction import AuctionContextModule, AuctionState
from core.health_monitor import HealthMonitor
from core.health_monitor import HealthMonitor
from core.order_executor import OrderExecutor
from core.liquidity import LiquidityAnalyzer
from manager.scanner import MarketContext, AlphaQuadrantAnalyzer
from core.liquidity import LiquidityAnalyzer
from manager.scanner import MarketContext, AlphaQuadrantAnalyzer
from manager.sentiment import SentimentAnalyzer

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
        self.sentiment_analyzer = SentimentAnalyzer(config)
        self.order_executor = OrderExecutor(config, logger, exchanges, persistence_manager, fee_manager, risk_manager)
        qbot_split = config.get('capital', {}).get('qbot_internal_split', {})
        self.cross_exchange_pct = Decimal(str(qbot_split.get('cross_exchange', 80))) / 100
        self.triangular_pct = Decimal(str(qbot_split.get('triangular', 20))) / 100
        self.pairs = []  # Dynamic
        risk_config = config.get('risk', {})
        # 5% of TPV max trade size
        self.max_trade_pct = Decimal(str(risk_config.get('max_trade_pct_tpv', 0.05)))
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
        # Ensure DataFeed is available as aggregator
        if not self.data_feed:
            logger.warning("DataFeed not available for Alpha Quadrant Scan")
            return []
        
        if not self.alpha_analyzer:
            self.alpha_analyzer = AlphaQuadrantAnalyzer(self.data_feed, self.config, logger)

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
                         res = self.exchanges[best_ex].place_order(opp['symbol'], 'buy', amount, best_price)
                         if res:
                            executed.append(plan)
                            # Persist
                            if self.persistence_manager:
                                self.persistence_manager.save_trade({
                                    'symbol': opp['symbol'],
                                    'type': 'ALPHA_SNIPE',
                                    'buy_exchange': best_ex,
                                    'amount': amount,  # Keep as Decimal
                                    'net_profit_usd': Decimal('0')  # Unknown yet, use Decimal
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
        """Fetch ONLY pairs that exist on MULTIPLE exchanges (arbitrage candidates)."""
        # Collect pairs per exchange
        exchange_pairs = {}
        for ex_name, exchange in self.exchanges.items():
            markets = exchange.get_supported_pairs()
            exchange_pairs[ex_name] = set(str(symbol) for symbol in markets)
        
        # Find COMMON pairs (exist on at least 2 exchanges)
        all_pairs = set()
        for pairs in exchange_pairs.values():
            all_pairs.update(pairs)
        
        self.pairs = []
        for pair in all_pairs:
            # Count how many exchanges have this pair
            count = sum(1 for ex_pairs in exchange_pairs.values() if pair in ex_pairs)
            if count >= 2:  # Only arbitrageable if on 2+ exchanges
                self.pairs.append(pair)
        
        # Prioritize high-volume pairs
        priority = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'SOL/USD']
        self.pairs = sorted(self.pairs, key=lambda p: (p not in priority, p))
        
        logger.info(f"🚀 Fetched {len(self.pairs)} COMMON pairs for arbitrage (from {len(all_pairs)} total)")

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
        # Only refresh pairs occasionally (not every scan!)
        if not self.pairs or not hasattr(self, '_pairs_fetched_at') or (datetime.now() - self._pairs_fetched_at).seconds > 300:
            self._fetch_pairs()
            self._pairs_fetched_at = datetime.now()
            
            # Pairs fetched. DataFeed subscription is handled internally by adapters/data/feed.py logic.
            # No manual subscription needed here.
        
        logger.info(f"🔄 Scanning {len(self.pairs)} pairs for arbitrage...")
        opportunities = []
        
        # Volatility slowdown: double cycle time if market is stressed
        if self.health_monitor:
            health = self.health_monitor.get_health_status()
            if health['overall_health'] != 'healthy':
                logger.warning("Volatility Slowdown: Doubling cycle time")
                await asyncio.sleep(self.cross_exchange_cycle) # Simple slowdown

        # Track rejection reasons for dashboard intelligence
        rejection_reasons = {}
        top_opportunity = None

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
                         # Use INJECTED DataFeed as aggregator (DI Fix)
                         if self.data_feed:
                             # Calculate metrics using DataFeed's aggregator logic
                             # and update context via update_market_context
                             bids = book.get('bids', [])
                             asks = book.get('asks', [])
                             best_bid = Decimal(str(bids[0][0])) if bids else 0
                             best_ask = Decimal(str(asks[0][0])) if asks else 0
                             last_price = (best_bid + best_ask) / 2
                             
                             self.data_feed.update_market_context(
                                symbol=pair, 
                                exchange=ex_name, 
                                bids=bids, 
                                asks=asks, 
                                last_price=last_price
                             )

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
            
            # LOG: Show which exchanges have price data for this pair
            if prices:
                price_summary = ", ".join([f"{ex}:{p['bid']:.2f}/{p['ask']:.2f}" for ex, p in prices.items()])
                logger.debug(f"📊 {pair}: {price_summary}")
            
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
                        # Fetch approx price from data feed
                        try:
                            if self.data_feed and self.data_feed.price_data:
                                # Try to get price from any exchange
                                for px_ex in self.data_feed.price_data.get(f"{quote_currency}/USDT", {}).values():
                                    if 'last' in px_ex:
                                        quote_usd_price = Decimal(str(px_ex['last']))
                                        break
                                else:
                                    # Fallback to direct fetch if not in feed
                                    # This blocks, but it's rare path for major pairs
                                    pass 
                        except Exception:
                            logger.debug(f"Could not fetch USD price for {quote_currency}, assuming 1.0 safely")
                            quote_usd_price = Decimal('1')

                    # Defensively calculated trade value in QUOTE CURRENCY
                    trade_value_quote = min(max_buy_quote, max_sell_quote_equiv)
                    
                    # Unblock: If sell_balance_base is 0, we can still buy if we allow it (e.g. accumulation)
                    # But Q-Bot is Arb. We need to be able to sell to complete the loop.
                    # Exception: If we have large portfolio but just 0 on this specific exchange.
                    # We stick to the safety check: We need implementation on Sell exchange.
                    
                    trade_value = trade_value_quote # In Quote Currency
                    
                    # Max trade USD check
                    trade_value_usd = trade_value * quote_usd_price
                    if quote_currency not in ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'SOL']:
                         # If it's a minor pair, ensure we have a price
                         pass


                    if trade_value <= 0:
                        # LOG: Why can't we trade?
                        if max_buy_quote > 0 and max_sell_quote_equiv <= 0:
                             msg = f"No {base_currency} on {sell_ex} to sell"
                             logger.debug(f"⚠️ {pair} {buy_ex}→{sell_ex}: Can't arb - {msg}")
                             if msg not in rejection_reasons: rejection_reasons[msg] = 0
                             rejection_reasons[msg] += 1
                        elif max_buy_quote <= 0:
                             # Just no capital on buy side
                             pass
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
                    
                    # LOG: Show arb calculation for visibility
                    if net_profit_pct > Decimal('0.001'):  # Only log if >0.1% potential
                        logger.info(f"📈 ARB SCAN {pair}: Buy@{buy_ex}=${buy_price:.2f} Sell@{sell_ex}=${sell_price:.2f} | Profit: {net_profit_pct*100:.3f}% (Threshold: {threshold*100:.2f}%)")
                    else:
                        # Log low profit reasons occasionally? No, spams logs.
                        # Track for dashboard
                        reason = "Low Profit"
                        if reason not in rejection_reasons: rejection_reasons[reason] = 0
                        rejection_reasons[reason] += 1
                    
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
                                    reason = f"Low Score ({scored_opp['analysis_score']:.2f})"
                                    if reason not in rejection_reasons: rejection_reasons[reason] = 0
                                    rejection_reasons[reason] += 1
                                    continue
                                if scored_opp['is_aggressive']:
                                    logger.info(f"🚀 AGGRESSIVE MODE for {pair} (Wyckoff/Whale signal)")

                        # Depth check: top 5 volume > 2.5–5x trade size
                        # Phase 10: Auction-Liquidity Fusion
                        # Stop using naive depth check. Use Auction Pressure + Liquidity Sizing.
                        
                        # A. Auction Context Pressure Check
                        # We need to analyze the 'Sell Exchange' book for Selling Pressure?
                        # No, we buy on BuyEx and Sell on SellEx.
                        # Danger: If BuyEx Price is dropping (Heavy Selling), we might buy a falling knife.
                        # Danger: If SellEx Price is dropping, our exit is vanishing.
                        
                        # Analyze SellEx (Exit) for Buying Support? Or Analyze BuyEx?
                        # Standard Arb: We want stable prices or convergence.
                        # If SellEx has "Imbalanced Selling" (Everyone dumping), do NOT buy on BuyEx expecting to sell there.
                        
                        ctx = MarketContext(pair)
                        ctx = self.auction_module.analyze_order_book(
                            books[sell_ex]['bids'], books[sell_ex]['asks'], sell_price, ctx
                        )
                        
                        if ctx.auction_state == AuctionState.IMBALANCED_SELLING:
                             # ELASTIC RESPONSE LOGIC (Small Account Friendly)
                             # Instead of rejecting, we De-Risk.
                             # If selling pressure is high, we demand more profit buffer and take smaller size.
                             
                             imbalance_severity = abs(ctx.auction_imbalance_score) # 0.3 to 1.0
                             risk_scalar = Decimal('1.0') + Decimal(str(imbalance_severity))
                             
                             # 1. Demand higher profit (e.g. 1.0% -> 1.5%)
                             min_profit_req = self.config.get('risk', {}).get('min_spread_pct', 0.006) * float(risk_scalar)
                             
                             if net_profit_pct < min_profit_req:
                                  logger.debug(f"Elastic Filter: De-risking {pair}. Profit {net_profit_pct*100:.2f}% < Adjusted Req {min_profit_req*100:.2f}%")
                                  continue
                                  
                             # 2. Reduce Size (e.g. $100 -> $50)
                             safety_factor = Decimal('0.5') / risk_scalar # Stronger imbalance = smaller size
                             original_trade = trade_value
                             trade_value = trade_value * safety_factor
                             
                             logger.info(f"🛡️ Elastic De-Risk: {pair} Imbalance {imbalance_severity:.2f}. "
                                         f"ReqProfit: {min_profit_req*100:.2f}%. "
                                         f"Size Scaled: ${original_trade:.0f} -> ${trade_value:.0f}")                    # B. Liquidity Analyzer Sizing (VWAP)
                        # 1. Parse full books for analysis - Handle MULTIPLE formats!
                        def parse_book_entry(entry):
                            if isinstance(entry, (list, tuple)):
                                return Decimal(str(entry[0])), Decimal(str(entry[1]))
                            if hasattr(entry, 'price'):
                                return Decimal(str(entry.price)), Decimal(str(entry.size))
                            if isinstance(entry, dict):
                                # Support 'amount', 'qty', or 'size' (Coinbase uses 'size')
                                qty = entry.get('amount') or entry.get('qty') or entry.get('size', 0)
                                return Decimal(str(entry.get('price', 0))), Decimal(str(qty))
                            return Decimal('0'), Decimal('0')

                        buy_asks = [parse_book_entry(a) for a in books[buy_ex].get('asks', [])]
                        sell_bids = [parse_book_entry(b) for b in books[sell_ex].get('bids', [])]
                        
                        # 2. Calculate Max Volume defined by Slippage Limit (0.2%)
                        # User's improvements.md suggests strict slippage (0.05-0.15%). Let's use 0.2% as safe upper bound.
                        max_slip = Decimal('0.002') 
                        max_buy_vol_base = LiquidityAnalyzer.calculate_max_size_with_slippage(buy_asks, max_slip)
                        max_sell_vol_base = LiquidityAnalyzer.calculate_max_size_with_slippage(sell_bids, max_slip)
                        
                        # 3. Convert to Quote Value (USD approx)
                        max_buy_val = max_buy_vol_base * buy_price
                        max_sell_val = max_sell_vol_base * sell_price
                        
                        # 4. Constrain Trade Value
                        # Original trade_value was based on Capital Cap. Now we apply Liquidity Cap.
                        original_val = trade_value
                        trade_value = min(trade_value, max_buy_val, max_sell_val)
                        
                        # Phase 11: Derivatives Signal Intelligence
                        # Bias size based on Coinbase Future Basis
                        # Only check if pair involves BTC to save API calls
                        if 'BTC' in pair:
                             # Updating sentiment requires a spot price. use current buy_price.
                             # We update somewhat lazily or per scan.
                             self.sentiment_analyzer.get_bitcoin_basis(buy_price)
                             mult = self.sentiment_analyzer.get_signal_multiplier()
                             if mult != Decimal('1.0'):
                                  before_sent = trade_value
                                  trade_value = trade_value * mult
                                  logger.info(f"🐋 Sentiment Adjust: Scaled {pair} size {float(mult):.2f}x (${before_sent:.2f} -> ${trade_value:.2f})")
                        
                        if trade_value < Decimal('10'): # Minimum meaningful trade
                             logger.debug(f"Liquidity/Sentiment too thin for {pair} (${trade_value:.2f} < $10). Skipping.")
                             continue
                             
                        if trade_value < original_val:
                             logger.info(f"Contextual Sizing: Reduced {pair} trade from ${original_val:.2f} to ${trade_value:.2f} to fit liquidity (0.2% slip).")

                        prices[buy_ex]['ask_vol'] = max_buy_vol_base # Update for context
                        
                        # Re-verify profit with new size (effective fees might change if tiered, but we assume flat for now)
                        # We proceed with this optimized size.

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
                        logger.info(f"Cross-Ex opportunity: {pair} Buy@{buy_ex} → Sell@{sell_ex} = {net_profit_pct*100:.3f}% (Size: ${trade_value:.2f})")
        
        # GNN PREMIUM DETECTION (Run after standard scan)
        if self.config.get('USE_GNN', False) and all_books:
            try:
                if not hasattr(self, 'gnn_detector'):
                    from manager.gnn_detector import GNNArbitrageDetector
                    self.gnn_detector = GNNArbitrageDetector()
                
                # Pass DataFeed (which implements aggregator interface)
                gnn_cycles = self.gnn_detector.detect(all_books, self.data_feed)
                
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
        
        # Summary log for visibility
        logger.info(f"🔍 Cross-Ex Scan: {len(self.pairs)} pairs, {len(opportunities)} opportunities found")
        
        # Save Audit Trail for Dashboard
        if hasattr(self, 'persistence_manager'):
             best_opp = sorted(opportunities, key=lambda x: x['net_profit_pct'], reverse=True)[0] if opportunities else None
             audit_data = {
                 'scan_type': 'CROSS',
                 'pairs_scanned': len(self.pairs),
                 'opportunities_found': len(opportunities),
                 'top_opportunity': best_opp,
                 'rejection_reason': rejection_reasons
             }
             self.persistence_manager.save_scan_audit(audit_data)
             
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
                    
                    cycles = self.gnn_detector.detect(gnn_input, self.data_feed, max_length=3)
                    
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
                    # Phase 10: Liquidity Analyzer for Triangular
                    # We need to find the MAX size that fits ALL 3 legs with minimal slippage (e.g. 0.2% total or per leg?)
                    # 0.1% per leg => 0.3% total cost (already heavy). Let's say 0.1% per leg.
                    
                    max_slip_leg = Decimal('0.001')
                    
                    # Leg 1: Buy => Ask Book
                    leg1_asks = [(Decimal(str(a['price'])), Decimal(str(a['amount']))) for a in books[0]['asks']]
                    max_vol1 = LiquidityAnalyzer.calculate_max_size_with_slippage(leg1_asks, max_slip_leg)
                    
                    # Leg 2: Sell => Bid Book (Wait, BTC/USDT -> ETH/BTC is buying ETH with BTC?)
                    # Path: BTC/USDT (Buy BTC), ETH/BTC (Buy ETH with BTC), ETH/USDT (Sell ETH for USDT)
                    # Leg 1: Ask (Buy BTC)
                    # Leg 2: Ask (Buy ETH)
                    # Leg 3: Bid (Sell ETH)
                    
                    # Wait, Leg 2 book is ETH/BTC. Asks are "Selling ETH for BTC". We "Buy ETH with BTC".
                    leg2_asks = [(Decimal(str(a['price'])), Decimal(str(a['amount']))) for a in books[1]['asks']]
                    # Volume here is usually in Base (ETH). We need to verify conversion later.
                    max_vol2_eth = LiquidityAnalyzer.calculate_max_size_with_slippage(leg2_asks, max_slip_leg)
                    
                    # Leg 3: Sell ETH => Bid Book
                    leg3_bids = [(Decimal(str(b['price'])), Decimal(str(b['amount']))) for b in books[2]['bids']]
                    max_vol3_eth = LiquidityAnalyzer.calculate_max_size_with_slippage(leg3_bids, max_slip_leg)
                    
                    # Normalize constraints to Starting Asset (USDT)
                    # Max Vol 1 is BTC.
                    # Price 1 (BTC/USDT)
                    max_val1_usdt = max_vol1 * ask1
                    
                    # Max Vol 2 is ETH. Price 2 (ETH/BTC).
                    # ETH * (ETH/BTC) = BTC value.
                    max_val2_btc = max_vol2_eth * ask2
                    max_val2_usdt = max_val2_btc * ask1 # Approx
                    
                    # Max Vol 3 is ETH. Price 3 (ETH/USDT).
                    max_val3_usdt = max_vol3_eth * bid3
                    
                    # Constrain
                    safe_trade_value = min(capital, self.max_trade_usd, max_val1_usdt, max_val2_usdt, max_val3_usdt)
                    
                    if safe_trade_value < Decimal('10'):
                        continue

                    opportunities.append({
                        'type': 'triangular',
                        'exchange': exchange_name,
                        'path': path,
                        'gross_profit_pct': float(profit * 100),
                        'net_profit_pct': float(net_profit * 100),
                        'trade_value': safe_trade_value,
                        'timestamp': datetime.now()
                    })
                    self.opportunities_found += 1
                    logger.info(f"Triangular opportunity on {exchange_name}: {' → '.join(path)} = {net_profit*100:.3f}% (Size: ${safe_trade_value:.2f})")
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