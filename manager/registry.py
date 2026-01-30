import logging
import time
import asyncio
from typing import Dict, Any, List, Optional
from decimal import Decimal
from threading import Lock

logger = logging.getLogger(__name__)

class MarketRegistry:
    """
    The Atomic Shared-State Registry (VRAM-like Buffer).
    Provides instant, thread-safe access to all exchange metadata.
    """
    def __init__(self):
        self._lock = Lock()
        self._asset_metadata: Dict[str, Dict[str, Any]] = {}  # exchange -> asset -> metadata
        self._market_metadata: Dict[str, Dict[str, Any]] = {} # exchange -> symbol -> metadata
        self._order_books: Dict[str, Dict[str, Any]] = {}    # exchange -> symbol -> book
        self._deposit_addresses: Dict[str, Dict[str, str]] = {} # exchange -> asset -> address
        self._last_update: Dict[str, float] = {}

    def update_book(self, exchange: str, symbol: str, book: Dict[str, Any]):
        with self._lock:
            if exchange not in self._order_books:
                self._order_books[exchange] = {}
            self._order_books[exchange][symbol] = book
            self._last_update[f"{exchange}_{symbol}_book"] = time.time()

    def get_order_book(self, exchange: str, symbol: str) -> Optional[Dict]:
        """Thread-safe retrieval of order book."""
        with self._lock:
            return self._order_books.get(exchange, {}).get(symbol)

    def get_all_books(self) -> Dict:
        """Thread-safe retrieval of ALL order books."""
        with self._lock:
            # Return deep copy or direct ref? Direct ref for speed, assuming read-only
            return {k: v.copy() for k, v in self._order_books.items()}

    def update_assets(self, exchange: str, data: Dict[str, Any]):
        with self._lock:
            if exchange not in self._asset_metadata:
                self._asset_metadata[exchange] = {}
            self._asset_metadata[exchange].update(data)
            self._last_update[f"{exchange}_assets"] = time.time()
            logger.debug(f"Registry updated assets for {exchange}")

    def update_markets(self, exchange: str, data: Dict[str, Any]):
        with self._lock:
            if exchange not in self._market_metadata:
                self._market_metadata[exchange] = {}
            self._market_metadata[exchange].update(data)
            self._last_update[f"{exchange}_markets"] = time.time()
            logger.debug(f"Registry updated markets for {exchange}")

    def update_address(self, exchange: str, asset: str, address: str):
        with self._lock:
            if exchange not in self._deposit_addresses:
                self._deposit_addresses[exchange] = {}
            self._deposit_addresses[exchange][asset] = address
            logger.debug(f"Registry updated address for {exchange}:{asset}")

    def get_fee(self, exchange: str, asset: str, network: str) -> Optional[Decimal]:
        """Instant access to withdrawal fees."""
        with self._lock:
            try:
                return self._asset_metadata[exchange][asset]['networks'][network]['withdraw_fee']
            except KeyError:
                return None

    def get_address(self, exchange: str, asset: str) -> Optional[str]:
        """Instant access to deposit addresses."""
        with self._lock:
            return self._deposit_addresses.get(exchange, {}).get(asset)

    def is_network_online(self, exchange: str, asset: str, network: str) -> bool:
        """Instant check for network maintenance."""
        with self._lock:
            try:
                return self._asset_metadata[exchange][asset]['networks'][network]['withdraw_enabled']
            except KeyError:
                return False

    def get_all_supported_symbols(self, exchange: str) -> List[str]:
        with self._lock:
            return list(self._market_metadata.get(exchange, {}).keys())

    def get_all_stakable_assets(self, exchange: str) -> List[str]:
        with self._lock:
            assets = []
            for asset, meta in self._asset_metadata.get(exchange, {}).items():
                if meta.get('can_stake', False):
                    assets.append(asset)
            return assets

    def get_supported_networks(self) -> List[str]:
        """Aggregate all supported networks across all exchanges/assets."""
        with self._lock:
            networks = set()
            for ex_data in self._asset_metadata.values():
                for asset_data in ex_data.values():
                    if 'networks' in asset_data:
                        for net in asset_data['networks'].keys():
                            networks.add(net)
            return list(networks)

class RegistryWorker:
    """
    Background worker that performs bulk API calls to keep the Registry fresh.
    Prevents IP bans by using bulk endpoints and controlled intervals.
    """
    def __init__(self, registry: MarketRegistry, exchanges: Dict[str, Any]):
        self.registry = registry
        self.exchanges = exchanges
        self.running = False

    async def start(self):
        self.running = True
        logger.info("Registry Worker started")
        # Initial sync
        await self.sync_all()
        while self.running:
            try:
                await asyncio.sleep(30) # High-speed metadata cycle
                await self.sync_all()
            except Exception as e:
                logger.error(f"Registry Worker sync error: {e}")
                await asyncio.sleep(5)

    async def sync_all(self):
        for name, adapter in self.exchanges.items():
            try:
                # 1. Bulk Market Metadata (Pairs, Precision, Status)
                if hasattr(adapter, 'get_market_metadata'):
                    markets = adapter.get_market_metadata()
                    self.registry.update_markets(name, markets)
                
                # 2. Bulk Asset Metadata (Fees, Networks, Staking Status)
                if hasattr(adapter, 'get_asset_metadata'):
                    assets = adapter.get_asset_metadata()
                    self.registry.update_assets(name, assets)

                # 3. Proactive Address Fetching for Arbitrage assets
                for asset in ['USDT', 'USDC', 'BTC', 'PAXG']:
                    if hasattr(adapter, 'fetch_deposit_address'):
                        try:
                            addr_info = adapter.fetch_deposit_address(asset)
                            if 'address' in addr_info:
                                self.registry.update_address(name, asset, addr_info['address'])
                        except:
                            continue
                
                logger.debug(f"Registry synced {name} successfully")
            except Exception as e:
                logger.warning(f"Registry failed to sync {name}: {e}")

    def stop(self):
        self.running = False
