import asyncio
import ccxt.pro as ccxtpro
import ccxt
import logging
import time
import statistics  # ADDED: Missing import for measure_network_latency
from typing import Dict, List, Callable
from adapters.data.ws import BinanceUSWebSocket, KrakenWebSocket, CoinbaseWebSocket
from manager.scanner import MarketContext, AuctionState, MarketPhase
from core.auction import AuctionContextModule

logger = logging.getLogger(__name__)

class DataFeed:
    """
    UNIFIED DATA ACQUISITION LAYER - WEB SOCKET ONLY
    - WebSocket mode only (REST polling is NOT SUPPORTED for our strategy)
    - Market Context & Auction Theory integration
    - Centralized balance tracking for dynamic capital mode
    - Automatic WebSocket reconnection and health monitoring
    """
    def __init__(self, config: Dict, main_logger: logging.Logger):
        self.config = config
        self.logger = main_logger
        self.exchanges = {}
        self.price_data = {}
        self.market_contexts = {}
        self.auction_analyzer = AuctionContextModule()
        self.data_callbacks = []
        
        # Capital Mode Support
        self.exchange_balances = {}  # exchange_name -> total_balance_usd
        self.latency_mode = 'LOW_LATENCY'  # Only WebSocket mode supported
        
        # Connection State
        self.running = False
        self.ws_connections = {}
        self.pro_exchanges = {}
        self.connection_health = {}
        self.reconnect_attempts = {}
        self.max_reconnect_attempts = 5
        
        # WebSocket monitoring
        self.last_data_received = {}
        self.data_timeout = 30  # seconds
        
        self.logger.info("✅ Unified DataFeed initialized (WebSocket-only mode)")
    
    # ==================== CAPITAL MODE INTEGRATION ====================
    def set_latency_mode(self, mode: str):
        """Set the data acquisition mode - ONLY WebSocket mode supported."""
        # Force LOW_LATENCY (WebSocket) mode regardless of input
        self.latency_mode = 'LOW_LATENCY'
        self.logger.info(f"📡 DataFeed mode forced to: {self.latency_mode} (REST polling not supported)")
    
    def get_total_balance_usd(self, exchange_name: str) -> float:
        """
        CRITICAL METHOD for Dynamic Capital Mode.
        Returns total balance in USD for a given exchange.
        Called by SystemOrchestrator._check_sufficient_balances().
        """
        try:
            # Return cached balance if available and recent
            if exchange_name in self.exchange_balances:
                cached_balance, timestamp = self.exchange_balances[exchange_name]
                if time.time() - timestamp < 30:  # Cache valid for 30 seconds
                    return cached_balance
            
            # Fetch fresh balance
            exchange = self.exchanges.get(exchange_name)
            if not exchange:
                self.logger.error(f"Exchange {exchange_name} not found in DataFeed")
                return 0.0
            
            # Fetch all balances
            balance = exchange.fetch_balance()
            
            # Calculate total in USD
            total_usd = 0.0
            btc_price = self._get_btc_price_for_exchange(exchange_name)
            
            for currency, amount in balance['total'].items():
                if amount <= 0:
                    continue
                    
                if currency in ['USDT', 'USDC', 'USD']:
                    total_usd += amount
                elif currency == 'BTC':
                    total_usd += amount * btc_price
                # Add other currencies as needed
            
            # Update cache
            self.exchange_balances[exchange_name] = (total_usd, time.time())
            
            self.logger.debug(f"💰 {exchange_name} total balance: ${total_usd:.2f}")
            return total_usd
            
        except Exception as e:
            self.logger.error(f"Error getting balance for {exchange_name}: {e}")
            return 0.0
    
    def _get_btc_price_for_exchange(self, exchange_name: str) -> float:
        """Get current BTC price in USD for an exchange."""
        try:
            # Try to get from price_data first
            for symbol_data in self.price_data.values():
                if exchange_name in symbol_data:
                    data = symbol_data[exchange_name]
                    return (data.get('bid', 0) + data.get('ask', 0)) / 2
            
            # Fallback: fetch fresh ticker via WebSocket-enabled exchange
            exchange = self.exchanges.get(exchange_name)
            if exchange:
                ticker = exchange.fetch_ticker('BTC/USDT')
                return ticker['last'] if ticker['last'] else ticker['bid']
                
        except Exception as e:
            self.logger.debug(f"Could not get BTC price for {exchange_name}: {e}")
        
        return 40000.0  # Conservative fallback
    
    def measure_network_latency(self) -> float:
        """Measure average network latency to exchanges."""
        latencies = []
        for name, exchange in self.exchanges.items():
            try:
                start = time.time()
                # Simple API call to measure latency
                exchange.fetch_time()
                latency = (time.time() - start) * 1000  # Convert to ms
                latencies.append(latency)
                self.logger.debug(f"   {name} latency: {latency:.1f}ms")
            except Exception as e:
                self.logger.debug(f"Latency check failed for {name}: {e}")
        
        return statistics.mean(latencies) if latencies else 500.0
    # ==================== END CAPITAL MODE INTEGRATION ====================
    
    def subscribe(self, callback: Callable):
        """Subscribe to real-time data updates."""
        self.data_callbacks.append(callback)
    
    async def _process_incoming_data(self, data: Dict):
        """Process data from any source and notify subscribers."""
        for callback in self.data_callbacks:
            try:
                await callback(data)
            except Exception as e:
                self.logger.error(f"Data callback error: {e}")
    
    def update_market_context(self, symbol: str, exchange: str, bids: List, asks: List, last_price: float):
        """Update market context with new order book data"""
        try:
            if symbol not in self.market_contexts:
                self.market_contexts[symbol] = MarketContext(primary_symbol=symbol)
            
            context = self.market_contexts[symbol]
            context.timestamp = time.time()
            
            # Update auction context
            context = self.auction_analyzer.analyze_order_book(bids, asks, last_price, context)
            
            # Update market phase based on auction state
            self._update_market_phase(context)
            
            # Update execution confidence
            self._update_execution_confidence(context)
            
            # Log significant context changes
            if context.auction_state != AuctionState.BALANCED:
                self.logger.debug(f"Market Context [{symbol}]: {context.to_dict()}")
                
        except Exception as e:
            self.logger.error(f"Error updating market context: {e}")
    
    def _update_market_phase(self, context: MarketContext):
        """Update market phase based on auction analysis"""
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
        """Update execution confidence based on market conditions"""
        # Higher confidence when there's clear auction direction
        if context.auction_state in [AuctionState.IMBALANCED_BUYING, AuctionState.IMBALANCED_SELLING]:
            context.execution_confidence = 0.9
        elif context.auction_state in [AuctionState.ACCEPTING, AuctionState.REJECTING]:
            context.execution_confidence = 0.7
        elif context.auction_state == AuctionState.BALANCED:
            context.execution_confidence = 0.5
        else:
            context.execution_confidence = 0.3
            
        # Adjust based on sentiment strength
        context.execution_confidence *= (1.0 + abs(context.market_sentiment))
    
    # ==================== WEB SOCKET MODE (ONLY MODE) ====================
    async def start_websocket_feed(self):
        """Start WebSocket connections - THE ONLY SUPPORTED MODE."""
        self.logger.info("🚀 Starting WebSocket data feed (REST polling is DISABLED)")
        
        # DEBUG: Log current state
        self.logger.info(f"🔧 DEBUG: latency_mode={self.latency_mode}")
        self.logger.info(f"🔧 DEBUG: config exchanges={list(self.config['exchanges'].keys())}")
        
        try:
            # Initialize authenticated exchanges
            await self._init_pro_exchanges()
            self.logger.info(f"🔧 DEBUG: pro_exchanges initialized: {list(self.pro_exchanges.keys())}")
            
            # Initialize custom WebSocket connections for redundancy
            await self._init_custom_websockets()
            self.logger.info(f"🔧 DEBUG: custom_websockets initialized: {list(self.ws_connections.keys())}")
            
            self.running = True
            
            # Start watching order books
            asyncio.create_task(self._watch_pro_orderbooks())
            
            # Start WebSocket health monitoring
            asyncio.create_task(self._monitor_websocket_health())
            
            # Start reconnection management
            asyncio.create_task(self._maintain_websocket_connections())
            
            # Verify we have connections
            total_connections = len(self.pro_exchanges) + len(self.ws_connections)
            self.logger.info(f"✅ WebSocket feed started with {total_connections} exchange connections")
            
            # Wait for initial data
            await asyncio.sleep(3)
            self.logger.info("✅ WebSocket data feed fully initialized and ready")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start WebSocket feed: {e}", exc_info=True)
            # DO NOT fall back to REST - raise and let orchestrator handle retry
            raise
    
    async def _init_pro_exchanges(self):
        """Initialize authenticated ccxt.pro exchanges."""
        exchange_configs = self.config.get('exchanges', {})
        
        for name, config in exchange_configs.items():
            if not config.get('enabled', False):
                continue
                
            try:
                # Common config
                pro_config = {
                    'apiKey': config.get('api_key', ''),
                    'secret': config.get('api_secret', ''),
                    'enableRateLimit': True,
                    'timeout': 30000,
                }
                
                # Exchange-specific initialization
                if name == 'binance':
                    self.pro_exchanges[name] = ccxtpro.binanceus(pro_config)
                elif name == 'kraken':
                    self.pro_exchanges[name] = ccxtpro.kraken(pro_config)
                elif name == 'coinbase':
                    self.pro_exchanges[name] = ccxtpro.coinbase(pro_config)
                else:
                    continue
                
                # Also store in regular exchanges dict for balance checks
                self.exchanges[name] = ccxt.__dict__[name]({
                    'apiKey': config.get('api_key', ''),
                    'secret': config.get('api_secret', ''),
                    'enableRateLimit': True
                })
                
                # Load markets
                await self.pro_exchanges[name].load_markets()
                self.exchanges[name].load_markets()
                
                # Initialize connection health tracking
                self.connection_health[name] = {
                    'status': 'connecting',
                    'last_success': None,
                    'errors': 0
                }
                self.reconnect_attempts[name] = 0
                
                self.logger.info(f"✅ {name.upper()} initialized (WebSocket)")
                
            except Exception as e:
                self.logger.error(f"❌ Failed to init {name}: {e}")
                self.connection_health[name] = {
                    'status': 'failed',
                    'last_success': None,
                    'errors': 1
                }
    
    async def _init_custom_websockets(self):
        """Initialize custom WebSocket connections."""
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
                
                # Initialize connection health tracking
                if name not in self.connection_health:
                    self.connection_health[name] = {
                        'status': 'connected',
                        'last_success': time.time(),
                        'errors': 0
                    }
                self.reconnect_attempts[name] = 0
                
                self.logger.info(f"✅ Custom WebSocket for {name.upper()} established")
                
            except Exception as e:
                self.logger.error(f"❌ Custom WebSocket init failed for {name}: {e}")
                if name not in self.connection_health:
                    self.connection_health[name] = {
                        'status': 'failed',
                        'last_success': None,
                        'errors': 1
                    }
    
    async def _handle_websocket_data(self, data: Dict):
        """Handle incoming WebSocket data from custom connections."""
        try:
            exchange = data.get('exchange', '')
            data_type = data.get('type', '')
            
            if data_type == 'orderbook':
                # Map exchange names
                if exchange == 'binance_us':
                    exchange = 'binance'
                    symbol = 'BTC/USDT'
                elif exchange == 'kraken':
                    symbol = 'BTC/USD'
                elif exchange == 'coinbase':
                    symbol = 'BTC/USD'
                else:
                    return
                
                # Update last data received timestamp
                self.last_data_received[exchange] = time.time()
                
                # Extract best bid/ask
                bids = data.get('bids', [])
                asks = data.get('asks', [])
                
                if bids and asks:
                    best_bid = float(bids[0][0]) if bids[0] else None
                    best_ask = float(asks[0][0]) if asks[0] else None
                    
                    if best_bid and best_ask:
                        # Update price data
                        if symbol not in self.price_data:
                            self.price_data[symbol] = {}
                        
                        self.price_data[symbol][exchange] = {
                            'bid': best_bid,
                            'ask': best_ask,
                            'bids': bids[:5],
                            'asks': asks[:5],
                            'timestamp': data.get('timestamp', time.time())
                        }
                        
                        # Update market context
                        last_price = (best_bid + best_ask) / 2
                        self.update_market_context(symbol, exchange, bids, asks, last_price)
                        
                        # Update connection health
                        if exchange in self.connection_health:
                            self.connection_health[exchange]['status'] = 'connected'
                            self.connection_health[exchange]['last_success'] = time.time()
                            self.connection_health[exchange]['errors'] = 0
                            self.reconnect_attempts[exchange] = 0
                        
                        # Notify subscribers
                        await self._process_incoming_data({
                            'type': 'price_update',
                            'symbol': symbol,
                            'exchange': exchange,
                            'bid': best_bid,
                            'ask': best_ask,
                            'timestamp': time.time()
                        })
                        
        except Exception as e:
            self.logger.error(f"WebSocket data handling error: {e}")
            if exchange in self.connection_health:
                self.connection_health[exchange]['errors'] += 1
    
    async def _watch_pro_orderbooks(self):
        """Watch order books using ccxt.pro."""
        tasks = []
        
        for name, pro_exch in self.pro_exchanges.items():
            # Determine symbols to watch
            symbols = ['BTC/USDT', 'BTC/USD']  # Monitor both
            
            for symbol in symbols:
                if hasattr(pro_exch, 'markets') and symbol in pro_exch.markets:
                    tasks.append(self._watch_single_book(name, pro_exch, symbol))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _watch_single_book(self, exch_name: str, exchange, symbol: str):
        """Watch a single order book."""
        while self.running:
            try:
                orderbook = await exchange.watch_order_book(symbol)
                
                # Update last data received timestamp
                self.last_data_received[exch_name] = time.time()
                
                if symbol not in self.price_data:
                    self.price_data[symbol] = {}
                
                # Extract best bid/ask
                best_bid = orderbook['bids'][0][0] if orderbook['bids'] else None
                best_ask = orderbook['asks'][0][0] if orderbook['asks'] else None
                
                if best_bid and best_ask:
                    self.price_data[symbol][exch_name] = {
                        'bid': best_bid,
                        'ask': best_ask,
                        'bids': orderbook['bids'][:5],
                        'asks': orderbook['asks'][:5],
                        'timestamp': orderbook['timestamp']
                    }
                    
                    # Update connection health
                    if exch_name in self.connection_health:
                        self.connection_health[exch_name]['status'] = 'connected'
                        self.connection_health[exch_name]['last_success'] = time.time()
                        self.connection_health[exch_name]['errors'] = 0
                        self.reconnect_attempts[exch_name] = 0
                    
                    # Update market context
                    last_price = (best_bid + best_ask) / 2
                    self.update_market_context(
                        symbol, 
                        exch_name, 
                        orderbook['bids'][:10], 
                        orderbook['asks'][:10], 
                        last_price
                    )
                    
                    # Notify subscribers
                    await self._process_incoming_data({
                        'type': 'price_update',
                        'symbol': symbol,
                        'exchange': exch_name,
                        'bid': best_bid,
                        'ask': best_ask,
                        'timestamp': time.time()
                    })
                
                # Small sleep to prevent overwhelming
                await exchange.sleep(0.01)
                
            except Exception as e:
                self.logger.error(f"ccxt.pro WebSocket error on {exch_name} {symbol}: {e}")
                
                # Update connection health
                if exch_name in self.connection_health:
                    self.connection_health[exch_name]['status'] = 'error'
                    self.connection_health[exch_name]['errors'] += 1
                
                await asyncio.sleep(5)
    
    # ==================== WEB SOCKET RECONNECTION LOGIC ====================
    
    async def _monitor_websocket_health(self):
        """Monitor WebSocket connection health and data flow."""
        while self.running:
            try:
                current_time = time.time()
                dead_connections = []
                
                for exchange, last_time in self.last_data_received.items():
                    if current_time - last_time > self.data_timeout:
                        self.logger.warning(f"⚠️  No data from {exchange} for {self.data_timeout}s")
                        if exchange in self.connection_health:
                            self.connection_health[exchange]['status'] = 'stale'
                        
                        # Check if we should attempt reconnection
                        if exchange in self.reconnect_attempts:
                            if self.reconnect_attempts[exchange] < self.max_reconnect_attempts:
                                self.logger.info(f"🔄 Attempting to reconnect {exchange}...")
                                await self._reconnect_exchange(exchange)
                
                # Log connection status periodically
                for exchange, health in self.connection_health.items():
                    status = health['status']
                    errors = health['errors']
                    if status != 'connected' or errors > 0:
                        self.logger.warning(f"🔧 {exchange}: status={status}, errors={errors}")
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                self.logger.error(f"WebSocket health monitoring error: {e}")
                await asyncio.sleep(10)
    
    async def _maintain_websocket_connections(self):
        """Maintain and reconnect WebSocket connections."""
        while self.running:
            try:
                # Check connection health
                for exchange_name, health in self.connection_health.items():
                    status = health['status']
                    
                    # If connection is failed or stale, attempt reconnection
                    if status in ['failed', 'stale']:
                        if self.reconnect_attempts.get(exchange_name, 0) < self.max_reconnect_attempts:
                            await self._reconnect_exchange(exchange_name)
                        else:
                            self.logger.error(f"❌ {exchange_name}: Max reconnection attempts reached")
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.logger.error(f"WebSocket maintenance error: {e}")
                await asyncio.sleep(30)
    
    async def _reconnect_exchange(self, exchange_name: str):
        """Attempt to reconnect to a specific exchange."""
        try:
            self.logger.info(f"🔄 Reconnecting to {exchange_name}...")
            
            # Increment reconnect attempts
            self.reconnect_attempts[exchange_name] = self.reconnect_attempts.get(exchange_name, 0) + 1
            
            # Try to reconnect based on exchange type
            if exchange_name in self.pro_exchanges:
                # Reinitialize ccxt.pro exchange
                exchange_configs = self.config.get('exchanges', {}).get(exchange_name, {})
                
                if exchange_configs.get('enabled', False):
                    pro_config = {
                        'apiKey': exchange_configs.get('api_key', ''),
                        'secret': exchange_configs.get('api_secret', ''),
                        'enableRateLimit': True,
                        'timeout': 30000,
                    }
                    
                    # Recreate exchange instance
                    if exchange_name == 'binance':
                        self.pro_exchanges[exchange_name] = ccxtpro.binanceus(pro_config)
                    elif exchange_name == 'kraken':
                        self.pro_exchanges[exchange_name] = ccxtpro.kraken(pro_config)
                    elif exchange_name == 'coinbase':
                        self.pro_exchanges[exchange_name] = ccxtpro.coinbase(pro_config)
                    
                    await self.pro_exchanges[exchange_name].load_markets()
                    self.logger.info(f"✅ {exchange_name.upper()} reconnected (ccxt.pro)")
            
            elif exchange_name in self.ws_connections:
                # Reconnect custom WebSocket
                if exchange_name == 'binance':
                    self.ws_connections['binance'] = BinanceUSWebSocket("btcusdt")
                    await self.ws_connections['binance'].connect()
                    self.ws_connections['binance'].subscribe(self._handle_websocket_data)
                elif exchange_name == 'kraken':
                    self.ws_connections['kraken'] = KrakenWebSocket("XBT/USD")
                    await self.ws_connections['kraken'].connect()
                    self.ws_connections['kraken'].subscribe(self._handle_websocket_data)
                elif exchange_name == 'coinbase':
                    self.ws_connections['coinbase'] = CoinbaseWebSocket("BTC-USD")
                    await self.ws_connections['coinbase'].connect()
                    self.ws_connections['coinbase'].subscribe(self._handle_websocket_data)
                
                self.logger.info(f"✅ {exchange_name.upper()} reconnected (custom WebSocket)")
            
            # Update connection health
            if exchange_name in self.connection_health:
                self.connection_health[exchange_name] = {
                    'status': 'reconnecting',
                    'last_success': time.time(),
                    'errors': 0
                }
            
            await asyncio.sleep(2)  # Give time for connection to stabilize
            
        except Exception as e:
            self.logger.error(f"❌ Failed to reconnect {exchange_name}: {e}")
            if exchange_name in self.connection_health:
                self.connection_health[exchange_name]['status'] = 'failed'
                self.connection_health[exchange_name]['errors'] += 1
    
    # ==================== PUBLIC INTERFACE ====================
    
    def start(self):
        """
        Start WebSocket data feed - REST polling is DISABLED.
        This is the PRIMARY ENTRY POINT called by SystemOrchestrator.
        """
        # Force WebSocket mode regardless of config
        self.latency_mode = 'LOW_LATENCY'
        
        self.logger.info("🚀 Starting DataFeed in WebSocket-only mode (REST polling DISABLED)")
        import threading
        
        async def _async_start():
            """Internal async start method - WebSocket only."""
            try:
                await self.start_websocket_feed()
                
                # Keep the event loop running for WebSocket connections
                while self.running:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                self.logger.error(f"❌ WebSocket feed failed: {e}")
                # Do NOT fall back to REST - let orchestrator handle restart
                raise
        
        def _run_async():
            """Run async start in background thread."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_async_start())
            except Exception as e:
                self.logger.error(f"WebSocket thread error: {e}")
            finally:
                loop.close()
        
        # Start WebSocket feed in background thread
        self._feed_thread = threading.Thread(target=_run_async, daemon=True)
        self._feed_thread.start()
        self.logger.info("✅ WebSocket data feed started in background thread")
    
    async def get_prices(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get current prices from WebSocket cache."""
        if not self.running:
            self.logger.warning("⚠️  WebSocket feed not running")
            return {}
        
        # Return cached WebSocket data
        result = {}
        for symbol in symbols:
            if symbol in self.price_data:
                result[symbol] = self.price_data[symbol].copy()
            else:
                result[symbol] = {}
        
        # Log if no data is available (normal during initialization)
        if not any(result.values()) and self.running:
            data_age = time.time() - min(self.last_data_received.values()) if self.last_data_received else float('inf')
            if data_age > 5:  # More than 5 seconds since last data
                self.logger.debug("Waiting for WebSocket data...")
        
        return result
    
    # Keep the async 'stop' method for internal use
    async def _async_stop(self):
        """Internal async method to stop all connections."""
        self.logger.info("🛑 Stopping WebSocket DataFeed")
        self.running = False
        
        # Close ccxt.pro exchanges
        for name, exch in self.pro_exchanges.items():
            try:
                await exch.close()
            except:
                pass
                
        # Close custom WebSocket connections
        for name, ws in self.ws_connections.items():
            try:
                await ws.ws.close()
            except:
                pass
        
        # Clear caches
        self.price_data.clear()
        self.exchange_balances.clear()
        
        self.logger.info("✅ WebSocket DataFeed stopped")
    
    def get_last_price(self, symbol: str) -> float:
        """Get last price for a symbol (used by fallback balance calculation)."""
        try:
            if symbol in self.price_data:
                for exchange_data in self.price_data[symbol].values():
                    if 'bid' in exchange_data and 'ask' in exchange_data:
                        return (exchange_data['bid'] + exchange_data['ask']) / 2
        except Exception as e:
            self.logger.debug(f"Could not get last price for {symbol}: {e}")
        
        return 40000.0  # Conservative fallback
    
    # ==================== ORCHESTRATOR COMPATIBILITY METHODS ====================
    
    def get_market_data(self):
        """
        COMPATIBILITY METHOD FOR system.py
        Returns market data in format: {exchange_id: {symbol: {'bid': X, 'ask': Y, 'last': Z}}}
        """
        market_data = {}
        
        # Check if price_data exists and has the expected structure
        if not hasattr(self, 'price_data') or not self.price_data:
            self.logger.warning("No price_data available in DataFeed.")
            return market_data
        
        try:
            # Iterate through all symbols in price_data (e.g., 'BTC/USDT')
            for symbol, exchange_dict in self.price_data.items():
                # Iterate through all exchanges for this symbol
                for exchange_id, price_info in exchange_dict.items():
                    
                    # Ensure the exchange entry exists in our result dict
                    if exchange_id not in market_data:
                        market_data[exchange_id] = {}
                    
                    # Extract bid, ask, last from the stored info.
                    # Use .get() for safety, default to 0.0 if missing.
                    bid = price_info.get('bid', 0.0)
                    ask = price_info.get('ask', 0.0)
                    last = price_info.get('last', 0.0)
                    
                    # If 'last' is missing, calculate a midpoint (common fallback)
                    if last == 0.0 and bid > 0 and ask > 0:
                        last = (bid + ask) / 2
                    
                    # Build the nested dictionary for this symbol on this exchange
                    market_data[exchange_id][symbol] = {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'timestamp': price_info.get('timestamp', time.time())
                    }
            
            self.logger.debug(f"Market data collected for {len(market_data)} exchanges.")
            
        except Exception as e:
            self.logger.error(f"Error collecting market data: {e}")
            # Return empty dict to prevent orchestrator crash
            return {}
        
        return market_data

    def stop(self):
        """
        COMPATIBILITY METHOD FOR system.py
        Synchronous wrapper to stop the DataFeed.
        Called by the orchestrator on shutdown.
        """
        self.logger.info("DataFeed.stop() compatibility method called")
        # Set the running flag to False to stop all loops
        self.running = False
        # The async loops (in the background thread) should check self.running and exit.
        try:
            self.logger.info("✅ WebSocket stop signal sent.")
        except Exception as e:
            self.logger.error(f"Error in stop() compatibility wrapper: {e}")
        return
    # ==================== END OF ORCHESTRATOR COMPATIBILITY METHODS ====================