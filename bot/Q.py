from utils.utils import log

class QBot:
    def __init__(self, config, transfer_manager):
        self.config = config
        self.transfer_manager = transfer_manager
        self.pairs = ['BTC/USDT', 'BTC/USDC', 'BTC/USD', 'SOL/USDT', 'SOL/USDC', 'SOL/USD', 'ETH/USDT', 'ETH/USDC', 'ETH/USD']

    def arbitrage(self, pool):
        max_size = pool * (self.config['max_trade_pct'] / 100)
        for pair in self.pairs:
            for ex1_name, ex1 in self.config['exchanges'].items():
                for ex2_name, ex2 in self.config['exchanges'].items():
                    if ex1_name == ex2_name:
                        # Triangular within exchange
                        base, quote = pair.split('/')
                        for inter in ['ETH', 'SOL', 'BTC'] if base != inter else []:
                            path = [f"{base}/{inter}", f"{inter}/{quote}", f"{quote}/{base}"]
                            try:
                                books = [ex1.fetch_order_book(p) for p in path]
                                ask1 = books[0]['asks'][0][0]
                                bid2 = books[1]['bids'][0][0]
                                bid3 = books[2]['bids'][0][0]
                                profit = (bid3 / ask1 * bid2 - 1) - self.get_fees(ex1, path)
                                if profit > self.config['min_profit'] / 100:
                                    amount = min(max_size, books[0]['asks'][0][1])
                                    self.execute_triangular(ex1, path, amount)
                                    log(f"Triangular arb on {ex1_name}: {profit}%")
                            except Exception as e:
                                log(f"Tri arb error: {e}")
                    else:
                        # Cross-exchange simple
                        try:
                            book1 = ex1.fetch_order_book(pair)
                            book2 = ex2.fetch_order_book(pair)
                            bid1 = book1['bids'][0][0]
                            ask2 = book2['asks'][0][0]
                            spread = (bid1 - ask2) / ask2
                            fees = self.get_fees(ex1, [pair]) + self.get_fees(ex2, [pair]) + self.transfer_manager.get_transfer_fee(ex2_name, ex1_name)[0]
                            if spread > fees + self.config['min_profit'] / 100:
                                amount = min(max_size, book2['asks'][0][1])
                                ex2.create_limit_buy_order(pair, amount, ask2)
                                self.transfer_manager.transfer(pair.split('/')[0], ex2_name, ex1_name, amount, pair.split('/')[0])
                                ex1.create_limit_sell_order(pair, amount, bid1)
                                log(f"Cross arb {pair} {ex2_name} to {ex1_name}: {spread}%")
                        except Exception as e:
                            log(f"Cross arb error: {e}")

    def get_fees(self, ex, paths):
        return sum([ex.calculate_fee('limit', 'maker', 'buy', 1, 1, p)['rate'] for p in paths])  # Approx

    def execute_triangular(self, ex, path, amount):
        ex.create_limit_buy_order(path[0], amount, ex.fetch_order_book(path[0])['asks'][0][0])
        ex.create_limit_sell_order(path[1], amount / ex.fetch_order_book(path[0])['asks'][0][0], ex.fetch_order_book(path[1])['bids'][0][0])
        ex.create_limit_buy_order(path[2], amount, ex.fetch_order_book(path[2])['asks'][0][0])