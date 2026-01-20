from utils.utils import log

class ABot:
    def __init__(self, config, staking_manager, transfer_manager):
        self.config = config
        self.staking = staking_manager
        self.transfer = transfer_manager
        self.positions = {}  # coin: {'amount':, 'exchange':, 'staked':}

    def manage_positions(self, pool):
        empty_slots = 6 - len(self.positions)
        if empty_slots > 0:
            self.fill_empty(empty_slots, pool / 6)

    def handle_signal(self, action, coin):
        if action == 'buy' and len(self.positions) < 6 and coin in self.config['a_bot_coins']:
            ex, price = self.best_buy(coin)
            amount = (pool / 6) / price  # Adjust to pool slot
            ex.create_market_buy_order(f"{coin}/USDT", amount)
            self.positions[coin] = {'amount': amount, 'exchange': ex.id, 'staked': self.staking.stake_coin(ex, coin, amount)}
            log(f"Bought {amount} {coin} on {ex.id}")
        elif action == 'sell' and coin in self.positions:
            pos = self.positions.pop(coin)
            self.staking.unstake(self.config['exchanges'][pos['exchange']], coin, pos['amount'])  # FIFO oldest
            ex = self.config['exchanges'][pos['exchange']]
            ex.create_market_sell_order(f"{coin}/USDT", pos['amount'])
            log(f"Sold {pos['amount']} {coin} on {ex.id}")

    def fill_empty(self, slots, amount_per):
        for _ in range(slots):
            coin = self.config['default_stake_coin']
            ex, price = self.best_buy(coin)
            amount = amount_per / price
            ex.create_market_buy_order(f"{coin}/USDT", amount)
            self.positions[coin] = {'amount': amount, 'exchange': ex.id, 'staked': self.staking.stake_coin(ex, coin, amount)}
            log(f"Filled empty with {amount} {coin}")

    def best_buy(self, coin):
        prices = {ex: ex.fetch_ticker(f"{coin}/USDT")['ask'] for ex in self.config['exchanges'].values() if f"{coin}/USDT" in ex.markets}
        best_ex = min(prices, key=prices.get)
        return best_ex, prices[best_ex]

    def liquidate(self):
        for coin in list(self.positions):
            self.handle_signal('sell', coin)