from utils.utils import log, shared_state

class GBot:
    def __init__(self, config, transfer_manager):
        self.config = config
        self.transfer = transfer_manager
        self.sweeps = 0

    def accumulate_paxg(self, pool):
        ex, price = self.best_buy()
        amount = pool / price
        ex.create_market_buy_order('PAXG/USDT', amount)
        log(f"Accumulated {amount} PAXG on {ex.id}")

    def sell_paxg(self, pct):
        for ex in self.config['exchanges'].values():
            bal = ex.fetch_balance().get('PAXG', {}).get('free', 0)
            sell_amt = bal * pct
            ex.create_market_sell_order('PAXG/USDT', sell_amt)
            log(f"Sold {sell_amt} PAXG on {ex.id}")

    def force_sweep(self):
        if self.sweeps < self.config['gold_sweep_max']:
            for ex in self.config['exchanges'].values():
                bal = ex.fetch_balance().get('PAXG', {}).get('free', 0) * 0.15
                ex.withdraw('PAXG', bal, self.config['cold_wallet'], {'network': 'ERC20'})
                shared_state['paxg_cold'] += bal
            self.sweeps += 1
            log("Gold sweep executed")
        else:
            log("Max sweeps reached")

    def best_buy(self):
        prices = {ex: ex.fetch_ticker('PAXG/USDT')['ask'] for ex in self.config['exchanges'].values() if 'PAXG/USDT' in ex.markets}
        best_ex = min(prices, key=prices.get)
        return best_ex, prices[best_ex]