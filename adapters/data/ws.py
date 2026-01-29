import asyncio
import json
import logging
import time
import websockets
import ssl
import certifi
from dotenv import load_dotenv
import os

load_dotenv('config/.env')


class BinanceUSWebSocket:
    def __init__(self, symbol: str = "btcusdt"):
        self.uri = f"wss://stream.binance.us:9443/ws/{symbol}@depth@100ms/{symbol}@trade"
        self.ws = None
        self.logger = logging.getLogger(__name__)
        self.callbacks = []

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            self.logger.info("✅ Binance.US WebSocket connected")
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Binance.US connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                await self._handle_message(data)
        except Exception as e:
            self.logger.error(f"Binance.US listen error: {e}")

    async def _handle_message(self, data: dict):
        msg_type = data.get('e')
        if msg_type == 'depthUpdate':
            book_data = {
                'exchange': 'binanceus',
                'type': 'orderbook',
                'bids': [[float(b[0]), float(b[1])] for b in data.get('b', [])[:10]],
                'asks': [[float(a[0]), float(a[1])] for a in data.get('a', [])[:10]],
                'timestamp': data.get('E')
            }
            await self._notify_callbacks(book_data)
        elif msg_type == 'trade':
            trade_data = {
                'exchange': 'binanceus',
                'type': 'trade',
                'price': float(data.get('p', 0)),
                'quantity': float(data.get('q', 0)),
                'timestamp': data.get('E')
            }
            await self._notify_callbacks(trade_data)

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

class KrakenWebSocket:
    def __init__(self, pair: str = "XBT/USD"):
        self.uri = "wss://ws.kraken.com"
        self.ws = None
        self.pair = pair
        self.logger = logging.getLogger(__name__)
        self.callbacks = []

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            self.logger.info("✅ Kraken WebSocket connected")
            subscribe_msg = {
                "event": "subscribe",
                "pair": [self.pair],
                "subscription": {"name": "book"}
            }
            await self.ws.send(json.dumps(subscribe_msg))
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Kraken connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                if isinstance(data, list) and len(data) > 3:
                    book_data = {
                        'exchange': 'kraken',
                        'type': 'orderbook',
                        'bids': [[float(b[0]), float(b[1]), float(b[2])] for b in data[1].get('b', [])[:10]],
                        'asks': [[float(a[0]), float(a[1]), float(a[2])] for a in data[1].get('a', [])[:10]],
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
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

class CoinbaseWebSocket:
    def __init__(self, product_ids: str = "BTC-USD"):
        self.uri = "wss://ws-feed.exchange.coinbase.com" # Legacy Pro URI
        self.ws = None
        self.product_ids = product_ids
        self.logger = logging.getLogger(__name__)
        self.callbacks = []

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            self.logger.info("✅ Coinbase (Regular) WebSocket connected")
            subscribe_msg = {
                "type": "subscribe",
                "channels": [{"name": "level2", "product_ids": [self.product_ids]}]
            }
            await self.ws.send(json.dumps(subscribe_msg))
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Coinbase Regular connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                if data.get('type') == 'snapshot' or data.get('type') == 'l2update':
                    book_data = {
                        'exchange': 'coinbase',
                        'type': 'orderbook',
                        'bids': [[float(b[0]), float(b[1])] for b in data.get('bids', [])[:10]],
                        'asks': [[float(a[0]), float(a[1])] for a in data.get('asks', [])[:10]],
                        'timestamp': time.time() * 1000
                    }
                    if data.get('type') == 'l2update':
                        # Simplification for update vs snapshot
                        book_data['bids'] = [[float(u[1]), float(u[2])] for u in data.get('changes', []) if u[0] == 'buy']
                        book_data['asks'] = [[float(u[1]), float(u[2])] for u in data.get('changes', []) if u[0] == 'sell']
                    
                    await self._notify_callbacks(book_data)
        except Exception as e:
            self.logger.error(f"Coinbase Regular listen error: {e}")

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

class CoinbaseAdvancedWebSocket:
    def __init__(self, product_ids: str = "BTC-USD"):
        self.uri = "wss://advanced-trade-ws.coinbase.com" 
        self.ws = None
        self.product_ids = product_ids
        self.logger = logging.getLogger(__name__)
        self.callbacks = []

    async def connect(self):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            self.logger.info("✅ Coinbase Advanced WebSocket connected")
            # Official pattern for Advanced Trade
            subscribe_msg = {
                "type": "subscribe",
                "product_ids": [self.product_ids],
                "channel": "l2_data"
            }
            await self.ws.send(json.dumps(subscribe_msg))
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Coinbase Advanced connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                # Official Advanced Trade WS format handling
                if 'channel' in data and data['channel'] == 'l2_data':
                    events = data.get('events', [])
                    for event in events:
                        if event.get('type') == 'snapshot' or event.get('type') == 'update':
                            updates = event.get('updates', [])
                            book_data = {
                                'exchange': 'coinbase_advanced',
                                'type': 'orderbook',
                                'bids': [[float(u['price']), float(u['new_quantity'])] for u in updates if u['side'] == 'bid'],
                                'asks': [[float(u['price']), float(u['new_quantity'])] for u in updates if u['side'] == 'offer'],
                                'timestamp': time.time() * 1000
                            }
                            await self._notify_callbacks(book_data)
                elif 'channel' in data and data['channel'] == 'level2':
                    # Support for standard level2 if used
                    book_data = {
                        'exchange': 'coinbase_advanced',
                        'type': 'orderbook',
                        'bids': [[float(b[0]), float(b[1])] for b in data.get('events', [])[0].get('updates', []) if b[0] == 'buy'],
                        'asks': [[float(a[0]), float(a[1])] for a in data.get('events', [])[0].get('updates', []) if a[0] == 'sell'],
                        'timestamp': time.time() * 1000
                    }
                    await self._notify_callbacks(book_data)
        except Exception as e:
            self.logger.error(f"Coinbase Advanced listen error: {e}")

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")