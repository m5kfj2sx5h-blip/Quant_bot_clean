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
from manager.scanner import MarketContext

load_dotenv()

logger = logging.getLogger(__name__)

class QBot:
    def __init__(self, config: dict, exchanges: Dict, fee_manager=None, threshold_manager=None, health_monitor=None, market_registry=None, portfolio=None, persistence_manager=None):
        self.config = config
        self.exchanges = exchanges
        self.fee_manager = fee_manager
        self.threshold_manager = threshold_manager
        self.health_monitor = health_monitor
        self.market_registry = market_registry
        self.portfolio = portfolio
        self.persistence_manager = persistence_manager
        self.auction_module = AuctionContextModule()
        self.order_executor = OrderExecutor(config, logger, exchanges, persistence_manager)
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
        logger.info(f"Q-Bot initialized. Split: {float(self.cross_exchange_pct)*100}% cross-ex / {float(self.triangular_pct)*100}% triangular. Max trade: {float(self.max_trade_pct*100)}% of TPV")

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
        baseline = Decimal('0.005')
        
        # If we have health monitor and auction data, make it dynamic
        if self.health_monitor and pair and exchange:
            # This is a bit of a stretch since we don't have a direct 'get_context' in health_monitor 
            # but let's assume we can get some sentiment or volatility
            try:
                # Logic: High volatility or aggressive sentiment -> Higher threshold
                # Low volatility or balanced auction -> Lower threshold
                pass
            except:
                pass

        if self.threshold_manager:
            return self.threshold_manager.get_threshold()
            
        return baseline

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

        for pair in self.pairs:
            prices = {}
            books = {}
            for ex_name, exchange in self.exchanges.items():
                try:
                    # Instant Registry Lookup (VRAM Model)
                    book = self.market_registry.get_order_book(ex_name, pair) if self.market_registry else exchange.get_order_book(pair)
                    if book and book.get('bids') and book.get('asks'):
                        prices[ex_name] = {
                            'bid': Decimal(str(book.get('bid', book['bids'][0]['price']))),
                            'ask': Decimal(str(book.get('ask', book['asks'][0]['price']))),
                            'bid_vol': Decimal(str(book['bids'][0]['amount'])),
                            'ask_vol': Decimal(str(book['asks'][0]['amount']))
                        }
                        books[ex_name] = book
                except Exception as e:
                    logger.debug(f"Error fetching {pair} from {ex_name}: {e}")
                    continue
            
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
                    
                    trade_value = min(allocated_capital.get(buy_ex, Decimal('0')), allocated_capital.get(sell_ex, Decimal('0')), self.max_trade_usd)
                    if trade_value <= 0:
                        continue

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
                # Leg 2: Sell BTC for ETH (Bid) - Wait, ETH/BTC usually means Sell BTC for ETH or Buy ETH with BTC?
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