""" STAKING MANAGER V 3.0.0 :
        - Advanced Dynamic Staking - fetches best APRs per exchange
        - Stakes Alpha bot's Idle money between BUY/SELL signals
        - Stakes 100% of idle Alpha capital in mix crypto/stable
        - Reserves last 2 positions in stable highest APR per account, buy if not held).
        """

import logging
from decimal import Decimal
import ccxt  # For dynamic APR
from core.order_executor import OrderExecutor  # For buy if not held


class StakingManager:
    def __init__(self, exchanges, config):
        # ...
        self.stable_reserve_slots = 2  # Last 2 for stable
        self.stable_coins = ['USDC', 'USDT', 'USDG']  # From research, dynamic in _get_aprs
        self.min_bond_short = self.config.get('staking', {}).get('min_bond_short', Decimal('7'))  # Days, user config
        self.min_bond_long = self.config.get('staking', {}).get('min_bond_long', Decimal('7'))  # Days for long
        self.exchanges = exchanges
        self.config = config
        self.min_apr = self.config.get('staking', {}).get('min_apr', Decimal('1.0'))  # User config
        self.min_rank = self.config.get('staking', {}).get('min_rank', 100)  # User config for safety
        self.slots = self.config['staking']['slots']
        self.staked = {}
        self.aprs = self._get_aprs()  # Dynamic
        self.order_executor = OrderExecutor()  # For buy/sell
        self.logger = logging.getLogger(__name__)

    def _get_aprs(self):
        aprs = {}
            for m in markets:
                coin = m['id']
                apr = Decimal(str(m.get('staking_apy', 0.0)))
                if apr < self.min_apr or m.get('market_cap_rank', 1000) > self.min_rank:
                    continue  # Filter low APY/presales (high rank = low cap)
                best_exchange = None
                max_apr = apr  # Base from CoinGecko
                for name, ex in self.exchanges.items():
                    try:
                        staking_info = ex.fetch_staking_rewards()
                        exchange_apr = Decimal(str(staking_info.get(coin, {}).get('apr', 0.0)))
                        if exchange_apr > max_apr:
                            max_apr = exchange_apr
                            best_exchange = name
                    except:
                        continue
                if best_exchange:
                    aprs[coin] = {'apr': max_apr, 'exchange': best_exchange}
                    self.logger.info(f"Fetched APR for {coin}: {max_apr}% on {best_exchange}")

                except Exception as e:
                self.logger.error(f"APR fetch failed: {e}—fallback to config")
                aprs = {coin: Decimal(str(self.config['staking']['aprs'][coin])) for coin in
                    self.config['staking']['coins']}
            return aprs

    def stake(self, coin, amount: Decimal):
        if coin not in self.coins:
            self.logger.error(f"⚠️ Invalid coin for staking: {coin}")
            return False
        if len(self.staked) >= self.slots:
            self.logger.error("⚠️ No staking slots available")
            return False

        # Buy if not held
        ex = self.exchanges[self.aprs[coin]['exchange']]
        held = ex.fetch_balance().get(coin, Decimal('0'))
        if held < amount:
            buy_amount = amount - held
            self.order_executor.execute_arbitrage(buy_exchange=ex.name, sell_exchange=None, buy_price=...,
                                                  symbol=coin + '/USDT', position_size=buy_amount,
                                                  expected_profit=Decimal('0'))  # Buy market/limit
            self.logger.info(f"✅ Bought {buy_amount.quantize(Decimal('0.00'))} {coin} for staking on {ex.name}")

        try:
            ex.stake(coin, str(amount))  # SDK/ccxt method
            self.staked[coin] = amount
            self.logger.info(
                f"Staked {amount.quantize(Decimal('0.00'))} {coin} on {self.aprs[coin]['exchange']} at {self.aprs[coin]['apr']}% APR")
            return True
        except Exception as e:
            self.logger.error(f"❌ Staking failed: {e}")
            return False

    def find_best_seat_warmers(self, idle_amount: Decimal, from_signals: bool = False):
        """Stake 100% idle in mix crypto/stable (reserve last 2 stable highest APR per account, buy if not held)."""
        sorted_aprs = sorted(self.aprs.items(), key=lambda x: x[1]['apr'], reverse=True)
        crypto_aprs = [item for item in sorted_aprs if item[0] not in self.stable_coins]
        stable_aprs = [item for item in sorted_aprs if item[0] in self.stable_coins]
        stake_count = self.slots - len(self.staked)
        if stake_count <= 0:
            return
        # Reserve stable for last 2
        if stake_count <= self.stable_reserve_slots:
            sorted_aprs = stable_aprs  # Only stable
        else:
            sorted_aprs = crypto_aprs + stable_aprs  # Mix
        per_stake = idle_amount / Decimal(stake_count)
        for coin, info in sorted_aprs:
            if len(self.staked) < self.slots:
                self.stake(coin, per_stake)

    def allocate(self, amount: Decimal):
        for coin in self.coins:
            if len(self.staked) >= self.slots:
                break
            stake_amount = amount / Decimal(len(self.coins))
            self.stake(coin, stake_amount)

    def unstake(self, coin, amount: Decimal = None):
        def unstake(self, coin, amount: Decimal = None):
        # Unstake short-term first on signal
        if coin not in self.staked:
            self.logger.error(f"No staking for {coin}")
            return False
        amount = amount or self.staked[coin]
        ex = self.exchanges[self.aprs[coin]['exchange']]
        try:
            ex.unstake(coin, str(amount))
            self.staked[coin] -= amount
            if self.staked[coin] <= Decimal('0'):
                del self.staked[coin]
            self.logger.info(f"✅ Unstaked {amount.quantize(Decimal('0.00'))} {coin} from {self.aprs[coin]['exchange']}")
            # Sell if needed (e.g., on signal)
            self.order_executor.execute_arbitrage(sell_exchange=ex.name, buy_exchange=None, sell_price=...,
                                                  symbol=coin + '/USDT', position_size=amount,
                                                  expected_profit=Decimal('0'))  # Sell time-sensitive
            return True
        except Exception as e:
            self.logger.error(f"❌ Unstaking failed: {e}")
            return False