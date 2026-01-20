from utils.utils import log

class TransferManager:
    def __init__(self, exchanges, stable, auto):
        self.exchanges = exchanges
        self.stable = stable
        self.auto = auto

    def balance_accounts(self):
        balances = {name: ex.fetch_balance().get('total', {}).get(self.stable, 0) for name, ex in self.exchanges.items()}
        avg = sum(balances.values()) / len(balances)
        for name, bal in balances.items():
            if bal < avg * 0.9:
                from_name = max(balances, key=balances.get)
                amount = (avg - bal) / 2
                fee, net = self.get_transfer_fee(from_name, name)
                if self.auto:
                    self.exchanges[from_name].withdraw(self.stable, amount, self.exchanges[name].fetch_deposit_address(self.stable)['address'], {'network': net})
                    log(f"Auto transfer {amount} {self.stable} from {from_name} to {name}")
                else:
                    log(f"Manual transfer needed: {amount} {self.stable} from {from_name} to {name} via {net}, fee {fee}")

    def get_transfer_fee(self, from_name, to_name):
        fees = self.exchanges[from_name].fetch_deposit_withdraw_fees([self.stable])
        nets = fees[self.stable]['networks']
        best_net = min(nets, key=lambda n: nets[n]['withdraw']['fee'])
        return nets[best_net]['withdraw']['fee'], best_net

    def transfer(self, asset, from_name, to_name, amount):
        if self.auto:
            net = 'TRC20' if 'TRC20' in self.exchanges[from_name].currencies[asset]['networks'] else 'ERC20'
            address = self.exchanges[to_name].fetch_deposit_address(asset)['address']
            self.exchanges[from_name].withdraw(asset, amount, address, {'network': net})