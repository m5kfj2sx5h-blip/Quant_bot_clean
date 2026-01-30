import asyncio
import json
import logging
import time
import websockets
import ssl
import certifi
from dotenv import load_dotenv
from typing import List, Callable
import os

load_dotenv('config/.env')

# HIGH-PRIORITY pairs for arbitrage (common across exchanges)
PRIORITY_PAIRS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOGE/USDT', 'MATIC/USDT',
    'DOT/USDT', 'LTC/USDT', 'LINK/USDT', 'AVAX/USDT', 'UNI/USDT', 'ATOM/USDT', 'XLM/USDT',
    'BTC/USD', 'ETH/USD', 'SOL/USD', 'XRP/USD', 'ADA/USD', 'LTC/USD',
    'BTC/USDC', 'ETH/USDC', 'SOL/USDC'
]


class BinanceUSWebSocket:
    """Multi-pair Binance.US WebSocket - subscribes to ALL priority pairs."""
    
    def __init__(self, symbols: List[str] = None):
        # Convert to Binance format: BTC/USDT -> btcusdt
        self.symbols = symbols or ['btcusdt', 'ethusdt', 'solusdt', 'xrpusdt', 'adausdt', 
                                    'dogeusdt', 'maticusdt', 'dotusdt', 'ltcusdt', 'linkusdt',
                                    'avaxusdt', 'uniusdt', 'atomusdt', 'xlmusdt']
        # Combined stream URL for multiple pairs
        streams = '/'.join([f"{s}@depth@100ms" for s in self.symbols])
        self.uri = f"wss://stream.binance.us:9443/stream?streams={streams}"
        self.ws = None
        self.logger = logging.getLogger(__name__)
        self.callbacks = []
        # Map binance symbol to standard format
        self.symbol_map = {s: s.upper().replace('USDT', '/USDT').replace('USD', '/USD').replace('USDC', '/USDC') 
                          for s in self.symbols}

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.ws.open

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            self.logger.info(f"✅ Binance.US WebSocket connected ({len(self.symbols)} pairs)")
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Binance.US connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                # Combined stream format: {"stream":"btcusdt@depth@100ms","data":{...}}
                if 'stream' in data and 'data' in data:
                    stream = data['stream']
                    payload = data['data']
                    symbol_raw = stream.split('@')[0]  # e.g., 'btcusdt'
                    await self._handle_message(payload, symbol_raw)
                elif 'e' in data:
                    # Single stream format
                    await self._handle_message(data, self.symbols[0] if self.symbols else 'btcusdt')
        except Exception as e:
            self.logger.error(f"Binance.US listen error: {e}")

    async def _handle_message(self, data: dict, symbol_raw: str):
        msg_type = data.get('e')
        # Convert symbol: btcusdt -> BTC/USDT
        symbol = symbol_raw.upper()
        if 'USDT' in symbol:
            symbol = symbol.replace('USDT', '/USDT')
        elif 'USDC' in symbol:
            symbol = symbol.replace('USDC', '/USDC')
        elif 'USD' in symbol:
            symbol = symbol.replace('USD', '/USD')
            
        if msg_type == 'depthUpdate':
            bids = data.get('b', [])
            asks = data.get('a', [])
            if bids or asks:
                book_data = {
                    'exchange': 'binanceus',
                    'symbol': symbol,
                    'type': 'orderbook',
                    'bids': [[float(b[0]), float(b[1])] for b in bids[:10]],
                    'asks': [[float(a[0]), float(a[1])] for a in asks[:10]],
                    'timestamp': data.get('E')
                }
                await self._notify_callbacks(book_data)

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except (TypeError, ValueError, KeyError) as e:
                self.logger.error(f"Callback data error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected callback error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")


class KrakenWebSocket:
    """Multi-pair Kraken WebSocket - subscribes to ALL priority pairs."""
    
    def __init__(self, pairs: List[str] = None):
        self.uri = "wss://ws.kraken.com"
        self.ws = None
        # Kraken uses XBT not BTC
        self.pairs = pairs or ["XBT/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD", 
                               "DOGE/USD", "DOT/USD", "LTC/USD", "LINK/USD", "ATOM/USD",
                               "XBT/USDT", "ETH/USDT", "SOL/USDT"]
        self.logger = logging.getLogger(__name__)
        self.callbacks = []
        # Map Kraken to standard: XBT/USD -> BTC/USD
        self.symbol_map = {'XBT': 'BTC', 'XDG': 'DOGE'}

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.ws.open

    def _normalize_symbol(self, kraken_symbol: str) -> str:
        """Convert Kraken symbol to standard: XBT/USD -> BTC/USD"""
        for k, v in self.symbol_map.items():
            kraken_symbol = kraken_symbol.replace(k, v)
        return kraken_symbol

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            self.logger.info(f"✅ Kraken WebSocket connected")
            # Subscribe to all pairs at once
            subscribe_msg = {
                "event": "subscribe",
                "pair": self.pairs,
                "subscription": {"name": "book", "depth": 10}
            }
            await self.ws.send(json.dumps(subscribe_msg))
            self.logger.info(f"✅ Kraken subscribed to {len(self.pairs)} pairs")
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Kraken connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                # Kraken format: [channelID, {"b":[...],"a":[...]}, "book-10", "XBT/USD"]
                if isinstance(data, list) and len(data) >= 4:
                    book_info = data[1]
                    pair_raw = data[-1]  # e.g., "XBT/USD"
                    symbol = self._normalize_symbol(pair_raw)
                    
                    if isinstance(book_info, dict):
                        # Snapshot or update
                        bids = book_info.get('bs', book_info.get('b', []))
                        asks = book_info.get('as', book_info.get('a', []))
                        
                        if bids or asks:
                            book_data = {
                                'exchange': 'kraken',
                                'symbol': symbol,
                                'type': 'orderbook',
                                'bids': [[float(b[0]), float(b[1])] for b in bids[:10]],
                                'asks': [[float(a[0]), float(a[1])] for a in asks[:10]],
                                'timestamp': time.time() * 1000
                            }
                            await self._notify_callbacks(book_data)
        except Exception as e:
            self.logger.error(f"Kraken listen error: {e}")

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except (TypeError, ValueError, KeyError) as e:
                self.logger.error(f"Callback data error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected callback error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")


class CoinbaseWebSocket:
    """Multi-pair Coinbase WebSocket - subscribes to ALL priority pairs."""
    
    def __init__(self, product_ids: List[str] = None):
        self.uri = "wss://ws-feed.exchange.coinbase.com"
        self.ws = None
        self.product_ids = product_ids or ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", 
                                            "ADA-USD", "DOGE-USD", "DOT-USD", "LTC-USD",
                                            "LINK-USD", "ATOM-USD", "AVAX-USD"]
        self.logger = logging.getLogger(__name__)
        self.callbacks = []
        self.order_books = {}  # Cache order books for incremental updates

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.ws.open

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context, max_size=10*1024*1024)
            self.logger.info(f"✅ Coinbase WebSocket connected")
            subscribe_msg = {
                "type": "subscribe",
                "channels": [{"name": "level2_batch", "product_ids": self.product_ids}]
            }
            await self.ws.send(json.dumps(subscribe_msg))
            self.logger.info(f"✅ Coinbase subscribed to {len(self.product_ids)} pairs")
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Coinbase connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                msg_type = data.get('type')
                product_id = data.get('product_id', '')
                symbol = product_id.replace('-', '/')  # BTC-USD -> BTC/USD
                
                if msg_type == 'snapshot':
                    # Full order book snapshot
                    self.order_books[symbol] = {
                        'bids': {b[0]: b[1] for b in data.get('bids', [])[:20]},
                        'asks': {a[0]: a[1] for a in data.get('asks', [])[:20]}
                    }
                    await self._emit_book(symbol)
                    
                elif msg_type == 'l2update':
                    # Incremental update
                    if symbol not in self.order_books:
                        self.order_books[symbol] = {'bids': {}, 'asks': {}}
                    
                    for change in data.get('changes', []):
                        side, price, size = change[0], change[1], change[2]
                        book_side = 'bids' if side == 'buy' else 'asks'
                        if float(size) == 0:
                            self.order_books[symbol][book_side].pop(price, None)
                        else:
                            self.order_books[symbol][book_side][price] = size
                    
                    await self._emit_book(symbol)
                    
        except Exception as e:
            self.logger.error(f"Coinbase listen error: {e}")

    async def _emit_book(self, symbol: str):
        if symbol not in self.order_books:
            return
        book = self.order_books[symbol]
        # Sort and format
        sorted_bids = sorted(book['bids'].items(), key=lambda x: float(x[0]), reverse=True)[:10]
        sorted_asks = sorted(book['asks'].items(), key=lambda x: float(x[0]))[:10]
        
        if sorted_bids and sorted_asks:
            book_data = {
                'exchange': 'coinbase',
                'symbol': symbol,
                'type': 'orderbook',
                'bids': [[float(p), float(s)] for p, s in sorted_bids],
                'asks': [[float(p), float(s)] for p, s in sorted_asks],
                'timestamp': time.time() * 1000
            }
            await self._notify_callbacks(book_data)

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except (TypeError, ValueError, KeyError) as e:
                self.logger.error(f"Callback data error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected callback error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")


class CoinbaseAdvancedWebSocket:
    """Multi-pair Coinbase Advanced WebSocket."""
    
    def __init__(self, product_ids: List[str] = None):
        self.uri = "wss://advanced-trade-ws.coinbase.com"
        self.ws = None
        self.product_ids = product_ids or ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD",
                                            "ADA-USD", "DOGE-USD", "LTC-USD", "LINK-USD"]
        self.logger = logging.getLogger(__name__)
        self.callbacks = []
        self.order_books = {}

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.ws.open

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context, max_size=10*1024*1024)
            self.logger.info(f"✅ Coinbase Advanced WebSocket connected")
            subscribe_msg = {
                "type": "subscribe",
                "product_ids": self.product_ids,
                "channel": "level2"
            }
            await self.ws.send(json.dumps(subscribe_msg))
            self.logger.info(f"✅ Coinbase Advanced subscribed to {len(self.product_ids)} pairs")
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Coinbase Advanced connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                channel = data.get('channel', '')
                
                if channel in ['l2_data', 'level2']:
                    for event in data.get('events', []):
                        product_id = event.get('product_id', '')
                        symbol = product_id.replace('-', '/')
                        
                        if event.get('type') == 'snapshot':
                            self.order_books[symbol] = {'bids': {}, 'asks': {}}
                            for update in event.get('updates', []):
                                side = 'bids' if update['side'] == 'bid' else 'asks'
                                self.order_books[symbol][side][update['price_level']] = update['new_quantity']
                            await self._emit_book(symbol)
                            
                        elif event.get('type') == 'update':
                            if symbol not in self.order_books:
                                self.order_books[symbol] = {'bids': {}, 'asks': {}}
                            for update in event.get('updates', []):
                                side = 'bids' if update['side'] == 'bid' else 'asks'
                                price = update['price_level']
                                qty = update['new_quantity']
                                if float(qty) == 0:
                                    self.order_books[symbol][side].pop(price, None)
                                else:
                                    self.order_books[symbol][side][price] = qty
                            await self._emit_book(symbol)
                            
        except Exception as e:
            self.logger.error(f"Coinbase Advanced listen error: {e}")

    async def _emit_book(self, symbol: str):
        if symbol not in self.order_books:
            return
        book = self.order_books[symbol]
        sorted_bids = sorted(book['bids'].items(), key=lambda x: float(x[0]), reverse=True)[:10]
        sorted_asks = sorted(book['asks'].items(), key=lambda x: float(x[0]))[:10]
        
        if sorted_bids and sorted_asks:
            book_data = {
                'exchange': 'coinbase_advanced',
                'symbol': symbol,
                'type': 'orderbook',
                'bids': [[float(p), float(s)] for p, s in sorted_bids],
                'asks': [[float(p), float(s)] for p, s in sorted_asks],
                'timestamp': time.time() * 1000
            }
            await self._notify_callbacks(book_data)

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except (TypeError, ValueError, KeyError) as e:
                self.logger.error(f"Callback data error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected callback error in {callback.__name__ if hasattr(callback, '__name__') else 'callback'}: {e}")