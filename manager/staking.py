import logging
from decimal import Decimal
from typing import Dict
from dotenv import load_dotenv
import time

load_dotenv('config/.env')

logger = logging.getLogger(__name__)

class StakingManager:
    def __init__(self, exchanges, config):
        self.exchanges = exchanges
        self.config = config
        self.min_apr = self.config.get('staking', {}).get('min_apr', Decimal('1.0'))
        self.min_rank = self.config.get('staking', {}).get('min_rank', 100)
        self.min_bond_short = self.config.get('staking', {}).get('min_bond_short', Decimal('7'))
        self.min_bond_long = self.config.get('staking', {}).get('min_bond_long', Decimal('7'))
        self.slots = self.config.get('staking', {}).get('slots', 6)
        self.staked = {}
        self.aprs = {}
        self._cache = {}
        self.cache_ttl = config.get('cache_ttl_minutes', 5) * 60
        self.retry_count = config.get('retry_count', 3)
        self._fetch_aprs()

    def _fetch_aprs(self):
        cache_key = 'staking_aprs'
        if cache_key in self._cache and time.time() - self._cache[cache_key]['timestamp'] < self.cache_ttl:
            self.aprs = self._cache[cache_key]['data']
            return
        self.aprs = {}
        for name, exchange in self.exchanges.items():
            for attempt in range(self.retry_count):
                try:
                    # Unified Port Access
                    staking_assets = exchange.get_staking_assets()
                    for asset in staking_assets:
                        # Normalize key names across SDKs inside the Adapter in next version
                        # but for now we handle common variations
                        coin = asset.get('symbol') or asset.get('coin') or asset.get('asset_id')
                        apr = Decimal(str(asset.get('apr') or asset.get('apy') or asset.get('reward_rate', 0.0)))
                        bond_days = Decimal(str(asset.get('bond_period_days') or asset.get('unbonding_period', 0)))
                        
                        if not coin or apr < self.min_apr:
                            continue
                        self.aprs[coin.upper()] = {'apr': apr, 'bond_days': bond_days, 'exchange': name}
                        logger.info(f"Ported staking rewards for {coin} on {name}: {apr}%")
                    break
                except Exception as e:
                    logger.warning(f"Staking fetch attempt {attempt+1} failed for {name}: {e}")
                    if attempt == self.retry_count - 1:
                        logger.error(f"Failed to fetch staking for {name}")
                    time.sleep(1)
        self._cache[cache_key] = {'data': self.aprs, 'timestamp': time.time()}

    def stake(self, coin, amount: Decimal):
        if coin not in self.aprs:
            logger.error(f"Warning: Invalid coin for staking: {coin}")
            return False
        
        ex_name = self.aprs[coin]['exchange']
        ex = self.exchanges[ex_name]
        
        try:
            logger.info(f"📤 Staking {amount.quantize(Decimal('0.0000'))} {coin} on {ex_name} at {self.aprs[coin]['apr']}% APR")
            ex.stake(coin, amount)
            self.staked[coin] = self.staked.get(coin, Decimal('0')) + amount
            return True
        except Exception as e:
            logger.error(f"❌ Staking failed for {coin} on {ex_name}: {e}")
            return False

    def get_highest_apy_coin(self) -> str:
        if not self.aprs:
            return None
        return max(self.aprs, key=lambda x: self.aprs[x]['apr'])

    def unstake(self, coin, amount: Decimal = None):
        if coin not in self.aprs:
            logger.error(f"Warning: No staking info for {coin}")
            return False
            
        amount = amount or self.staked.get(coin, Decimal('0'))
        if amount <= 0:
            return True

        ex_name = self.aprs[coin]['exchange']
        ex = self.exchanges[ex_name]
        
        try:
            logger.info(f"📥 Unstaking {amount.quantize(Decimal('0.0000'))} {coin} from {ex_name}")
            ex.unstake(coin, amount)
            if coin in self.staked:
                self.staked[coin] -= amount
                if self.staked[coin] <= Decimal('0'):
                    del self.staked[coin]
            return True
        except Exception as e:
            logger.error(f"❌ Unstaking failed for {coin} from {ex_name}: {e}")
            return False