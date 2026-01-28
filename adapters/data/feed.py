import asyncio
import logging
import time
import statistics
from decimal import Decimal
from typing import Dict, List, Callable, Any
from adapters.data.ws import BinanceUSWebSocket, KrakenWebSocket, CoinbaseWebSocket, CoinbaseAdvancedWebSocket
from manager.scanner import MarketContext, AuctionState, MarketPhase
from core.auction import AuctionContextModule
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)

class DataFeed:
    """ UNIFIED DATA ACQUISITION LAYER - WEB SOCKET ONLY """
    def __init__(self, config: Dict, main_logger: logging.Logger, registry: Any = None):
        self.config = config
        self.logger = main_logger
        self.registry = registry
        self.exchanges = {}
        self.price_data = {}
        self.market_contexts = {}
        self.auction_analyzer = AuctionContextModule()
        self.data_callbacks = []
        self.exchange_balances = {}  # exchange_name -> total_balance_usd
        self.latency_mode = 'LOW_LATENCY'
        self.running = False
        self.ws_connections = {}
        self.connection_health = {}
        self.reconnect_attempts = {}
        self.max_reconnect_attempts = 5
        self.last_data_received = {}
        self.data_timeout = 30
        self.logger.info("✅ Unified DataFeed initialized (WebSocket-only mode)")

    def set_latency_mode(self, mode: str):
        self.latency_mode = 'LOW_LATENCY'
        self.logger.info(f"📡 DataFeed mode forced to: {self.latency_mode} (REST polling not supported)")

    def get_total_balance_usd(self, exchange_name: str) -> float:
        try:
            if exchange_name in self.exchange_balances:
                cached_balance, timestamp = self.exchange_balances[exchange_name]
                if time.time() - timestamp < 30:
                    return cached_balance
            exchange = self.exchanges.get(exchange_name)
            if not exchange:
                self.logger.error(f"Exchange {exchange_name} not found in DataFeed")
                return 0.0
            balance = exchange.get_balance()
            total_usd = 0.0
            btc_price = self._get_btc_price_for_exchange(exchange_name)
            for currency, amount in balance.items():
                if amount <= 0:
                    continue
                if currency in ['USDT', 'USDC', 'USD']:
                    total_usd += amount
                elif currency == 'BTC':
                    total_usd += amount * btc_price
            self.exchange_balances[exchange_name] = (total_usd, time.time())
            self.logger.info(f"Fetched balances from API for {exchange_name}")
            return total_usd
        except Exception as e:
            self.logger.error(f"Error getting balance for {exchange_name}: {e}")
            return 0.0

    def _get_btc_price_for_exchange(self, exchange_name: str) -> float:
        try:
            for symbol_data in self.price_data.values():
                if exchange_name in symbol_data:
                    data = symbol_data[exchange_name]
                    return (data.get('bid', 0) + data.get('ask', 0)) / 2
            exchange = self.exchanges.get(exchange_name)
            if exchange:
                ticker = exchange.get_ticker_price('BTC/USDT')
                return ticker.value
        except Exception as e:
            self.logger.debug(f"Could not get BTC price for {exchange_name}: {e}")
        
        # Last resort: Try to find ANY price in registry
        if self.registry:
            for ex in ['binance', 'kraken', 'coinbase', 'coinbase_advanced']:
                book = self.registry.get_order_book(ex, 'BTC/USDT') or self.registry.get_order_book(ex, 'BTC/USD')
                if book:
                    return float(book.get('bid', book['bids'][0]['price']))
                    
        return 0.0 # Return 0 instead of fake price to prevent bad trades

    def subscribe(self, callback: Callable):
        self.data_callbacks.append(callback)

    async def _process_incoming_data(self, data: Dict):
        for callback in self.data_callbacks:
            try:
                await callback(data)
            except Exception as e:
                self.logger.error(f"Data callback error: {e}")

    def update_market_context(self, symbol: str, exchange: str, bids: List, asks: List, last_price: float, trades: List = None):
        try:
            if symbol not in self.market_contexts:
                self.market_contexts[symbol] = MarketContext(primary_symbol=symbol)
            context = self.market_contexts[symbol]
            context.timestamp = time.time()
            
            # Feed granular data to context
            if trades:
                for t in trades:
                    context.add_trade(Decimal(str(t.get('price'))), Decimal(str(t.get('quantity'))), t.get('side', 'unknown'))

            context = self.auction_analyzer.analyze_order_book(bids, asks, last_price, context)
            self._update_market_phase(context)
            self._update_execution_confidence(context)
            if context.auction_state != AuctionState.BALANCED:
                self.logger.debug(f"Market Context [{symbol}]: {context.to_dict()}")
        except Exception as e:
            self.logger.error(f"Error updating market context: {e}")

    def _update_market_phase(self, context: MarketContext):
        if context.auction_state == AuctionState.IMBALANCED_BUYING:
            context.market_phase = MarketPhase.ACCUMULATION
            context.market_sentiment = 0.8
        elif context.auction_state == AuctionState.IMBALANCED_SELLING:
            context.market_phase = MarketPhase.DISTRIBUTION
            context.market_sentiment = -0.8
        elif context.auction_state == AuctionState.ACCEPTING:
            context.market_phase = MarketPhase.MARKUP
            context.market_sentiment = 0.5
        elif context.auction_state == AuctionState.REJECTING:
            context.market_phase = MarketPhase.MARKDOWN
            context.market_sentiment = -0.5
        else:
            context.market_phase = MarketPhase.UNKNOWN
            context.market_sentiment = 0.0

    def _update_execution_confidence(self, context: MarketContext):
        if context.auction_state in [AuctionState.IMBALANCED_BUYING, AuctionState.IMBALANCED_SELLING]:
            context.execution_confidence = 0.9
        elif context.auction_state in [AuctionState.ACCEPTING, AuctionState.REJECTING]:
            context.execution_confidence = 0.7
        elif context.auction_state == AuctionState.BALANCED:
            context.execution_confidence = 0.5
        else:
            context.execution_confidence = 0.3
        context.execution_confidence *= (1.0 + abs(context.market_sentiment))

    async def start_websocket_feed(self):
        self.logger.info("Starting WebSocket data feed (REST polling is DISABLED)")
        try:
            await self._init_custom_websockets()
            self.running = True
            asyncio.create_task(self._monitor_websocket_health())
            asyncio.create_task(self._maintain_websocket_connections())
            total_connections = len(self.ws_connections)
            self.logger.info(f"WebSocket feed started with {total_connections} exchange connections")
            await asyncio.sleep(3)
            self.logger.info("WebSocket data feed fully initialized and ready")
        except Exception as e:
            self.logger.error(f"Failed to start WebSocket feed: {e}", exc_info=True)
            raise

    async def _init_custom_websockets(self):
        exchange_configs = self.config.get('exchanges', {})
        for name, config in exchange_configs.items():
            if not config.get('enabled', False):
                continue
            try:
                if name == 'binance':
                    binance_ws = BinanceUSWebSocket("btcusdt")
                    await binance_ws.connect()
                    binance_ws.subscribe(self._handle_websocket_data)
                    self.ws_connections['binance'] = binance_ws
                elif name == 'kraken':
                    kraken_ws = KrakenWebSocket("XBT/USD")
                    await kraken_ws.connect()
                    kraken_ws.subscribe(self._handle_websocket_data)
                    self.ws_connections['kraken'] = kraken_ws
                elif name == 'coinbase':
                    coinbase_ws = CoinbaseWebSocket("BTC-USD")
                    await coinbase_ws.connect()
                    coinbase_ws.subscribe(self._handle_websocket_data)
                    self.ws_connections['coinbase'] = coinbase_ws
                elif name == 'coinbase_advanced':
                    coinbase_adv_ws = CoinbaseAdvancedWebSocket("BTC-USD")
                    await coinbase_adv_ws.connect()
                    coinbase_adv_ws.subscribe(self._handle_websocket_data)
                    self.ws_connections['coinbase_advanced'] = coinbase_adv_ws
                self.connection_health[name] = {'status': 'connected', 'last_success': time.time(), 'errors': 0}
                self.reconnect_attempts[name] = 0
                self.logger.info(f"Custom WebSocket for {name.upper()} established")
            except Exception as e:
                self.logger.error(f"Custom WebSocket init failed for {name}: {e}")
                self.connection_health[name] = {'status': 'failed', 'last_success': None, 'errors': 1}

    async def _handle_websocket_data(self, data: Dict):
        try:
            exchange = data.get('exchange', '')
            data_type = data.get('type', '')
            if data_type == 'orderbook':
                if exchange == 'binance_us':
                    exchange = 'binance'
                    symbol = 'BTC/USDT'
                elif exchange == 'kraken':
                    symbol = 'BTC/USD'
                elif exchange == 'coinbase':
                    symbol = 'BTC/USD'
                elif exchange == 'coinbase_advanced':
                    symbol = 'BTC/USD'
                else:
                    return
                self.last_data_received[exchange] = time.time()
                bids = data.get('bids', [])
                asks = data.get('asks', [])
                if bids and asks:
                        best_bid = Decimal(str(bids[0][0])) if bids[0] else None
                        best_ask = Decimal(str(asks[0][0])) if asks[0] else None
                        if best_bid and best_ask:
                            if symbol not in self.price_data:
                                self.price_data[symbol] = {}
                            self.price_data[symbol][exchange] = {
                                'bid': best_bid,
                                'ask': best_ask,
                                'bids': [{'price': Decimal(str(p[0])), 'amount': Decimal(str(p[1]))} for p in bids[:5]],
                                'asks': [{'price': Decimal(str(p[0])), 'amount': Decimal(str(p[1]))} for p in asks[:5]],
                                'timestamp': data.get('timestamp', time.time())
                            }
                            # Push to Registry for 0ms access by other components
                            if self.registry:
                                self.registry.update_book(exchange, symbol, self.price_data[symbol][exchange])
                            
                            last_price = (best_bid + best_ask) / Decimal('2')
                        self.update_market_context(symbol, exchange, bids, asks, last_price)
                if exchange in self.connection_health:
                    self.connection_health[exchange]['status'] = 'connected'
                    self.connection_health[exchange]['last_success'] = time.time()
                    self.connection_health[exchange]['errors'] = 0
                    self.reconnect_attempts[exchange] = 0
                await self._process_incoming_data({
                    'type': 'price_update',
                    'symbol': symbol,
                    'exchange': exchange,
                    'bid': best_bid,
                    'ask': best_ask
                })
        except Exception as e:
            self.logger.error(f"Error handling WebSocket data: {e}")

    async def _monitor_websocket_health(self):
        while self.running:
            for name in list(self.ws_connections.keys()):
                if name in self.last_data_received:
                    if time.time() - self.last_data_received[name] > self.data_timeout:
                        self.logger.warning(f"No data from {name} for {self.data_timeout}s - reconnecting")
                        await self._reconnect(name)
            await asyncio.sleep(10)

    async def _reconnect(self, name: str):
        if self.reconnect_attempts.get(name, 0) >= self.max_reconnect_attempts:
            self.logger.error(f"Max reconnect attempts reached for {name}")
            return
        self.reconnect_attempts[name] = self.reconnect_attempts.get(name, 0) + 1
        try:
            await self.ws_connections[name].connect()
            self.connection_health[name] = {'status': 'connected', 'last_success': time.time(), 'errors': 0}
            self.reconnect_attempts[name] = 0
        except Exception as e:
            self.logger.error(f"Reconnect failed for {name}: {e}")
            self.connection_health[name]['errors'] += 1

    async def _maintain_websocket_connections(self):
        while self.running:
            for name, status in list(self.connection_health.items()):
                if status['status'] == 'failed':
                    await self._reconnect(name)
            await asyncio.sleep(60)