import asyncio
import json
import logging
import time
import websockets

class BinanceUSWebSocket:
    def __init__(self, symbol: str = "btcusdt"):
        self.uri = f"wss://stream.binance.us:9443/ws/{symbol}@depth@100ms/{symbol}@trade"
        self.ws = None
        self.logger = logging.getLogger(__name__)
        self.callbacks = []

    async def connect(self):
        try:
            self.ws = await websockets.connect(self.uri)
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
                'exchange': 'binance_us',
                'type': 'orderbook',
                'bids': [[float(b[0]), float(b[1])] for b in data.get('b', [])[:10]],
                'asks': [[float(a[0]), float(a[1])] for a in data.get('a', [])[:10]],
                'timestamp': data.get('E')
            }
            await self._notify_callbacks(book_data)
        elif msg_type == 'trade':
            trade_data = {
                'exchange': 'binance_us',
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
            self.ws = await websockets.connect(self.uri)
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
        self.uri = "wss://advanced-trade-ws.coinbase.com"
        self.ws = None
        self.product_ids = product_ids
        self.logger = logging.getLogger(__name__)
        self.callbacks = []

    async def connect(self):
        try:
            self.ws = await websockets.connect(self.uri)
            self.logger.info("✅ Coinbase WebSocket connected")
            subscribe_msg = {
                "type": "subscribe",
                "channel": "level2",
                "product_ids": [self.product_ids]
            }
            await self.ws.send(json.dumps(subscribe_msg))
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Coinbase connection failed: {e}")
            raise

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                if data.get('channel') == 'level2':
                    book_data = {
                        'exchange': 'coinbase',
                        'type': 'orderbook',
                        'bids': [[float(b[0]), float(b[1])] for b in data.get('bids', [])[:10]],
                        'asks': [[float(a[0]), float(a[1])] for a in data.get('asks', [])[:10]],
                        'timestamp': time.time() * 1000
                    }
                    await self._notify_callbacks(book_data)
        except Exception as e:
            self.logger.error(f"Coinbase listen error: {e}")

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def _notify_callbacks(self, data: dict):
        for callback in self.callbacks:
            try:
                await callback(data)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")
