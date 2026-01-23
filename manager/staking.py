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
        self.exchanges = exchanges
        self.config = config
        self.min_apr = self.config.get('staking', {}).get('min_apr', Decimal('1.0'))  # User config
        self.min_rank = self.config.get('staking', {}).get('min_rank', 100)  # User config for safety
        self.min_bond_short = self.config.get('staking', {}).get('min_bond_short', Decimal('7'))  # Days, user config
        self.min_bond_long = self.config.get('staking', {}).get('min_bond_long', Decimal('7'))  # Days for long
        self.slots = self.config['staking']['slots']
        self.staked = {}
        self.aprs = self._get_aprs()  # Dynamic
        self.order_executor = OrderExecutor()  # For buy/sell
        self.logger = logging.getLogger(__name__)

    def _get_aprs(self):
        aprs = {}
        try:
            coingecko = ccxt.coingecko()
            markets = coingecko.fetch_markets(params={'vs_currency': 'usd', 'order': 'staking_apy_desc', 'per_page': 50,
                                                      'page': 1})  # Fetch top 50 by APY
            for m in markets:
                coin = m['id']
                apr = Decimal(str(m.get('staking_apy', 0.0)))
                bond_days = Decimal(str(m.get('staking_bond_period_days', 0)))  # From CoinGecko
                if apr < self.min_apr or m.get('market_cap_rank', 1000) > self.min_rank:
                    continue  # Filter low APY/presales
                best_exchange = None
                max_apr = apr
                for name, ex in self.exchanges.items():
                    try:
                        staking_info = ex.fetch_staking_rewards()
                        exchange_apr = Decimal(str(staking_info.get(coin, {}).get('apr', 0.0)))
                        exchange_bond = Decimal(str(staking_info.get(coin, {}).get('bond_period_days', 0)))
                        if exchange_apr > max_apr:
                            max_apr = exchange_apr
                            bond_days = exchange_bond
                            best_exchange = name
                    except:
                        continue
                if best_exchange:
                    aprs[coin] = {'apr': max_apr, 'bond_days': bond_days, 'exchange': best_exchange}
                    self.logger.info(f"✅ Fetched APR for {coin}: {max_apr}% on {best_exchange} (bond: {bond_days} days)")
        except Exception as e:
            self.logger.error(f"⚠️ APR fetch failed: {e}—fallback to config")
            aprs = {coin: {'apr': Decimal(str(self.config['staking']['aprs'][coin])), 'bond_days': Decimal('0'),
                           'exchange': 'binanceus'} for coin in self.config['staking']['coins']}
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

    def find_best_seat_warmers(self, idle_amount: Decimal, high_idle: bool = False):
        """Stake 100% idle in multiple highest APR dynamic coins (long for committed/high-idle/signals, short for remaining/empty, buy if not held)."""
        sorted_aprs = sorted(self.aprs.items(), key=lambda x: x[1]['apr'], reverse=True)
        stake_count = self.slots - len(self.staked)
        if stake_count <= 0:
            return
        per_stake = idle_amount / Decimal(stake_count)
        for coin, info in sorted_aprs:
            if len(self.staked) < self.slots:
                if high_idle or from_signals:  # Long-term for high-idle/signals
                    if info['bond_days'] > self.min_bond_long:
                        self.stake(coin, per_stake)
                else:  # Short-term for remaining/empty
                    if info['bond_days'] < self.min_bond_short:
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