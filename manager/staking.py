import requests
from utils.utils import log

class StakingManager:
    def __init__(self, exchanges):
        self.exchanges = exchanges

    def stake_coin(self, ex, coin, amount):
        if ex.id == 'kraken':
            # Kraken staking endpoint
            headers = ex.sign('/0/private/Stake', 'post', {}, {'asset': coin, 'amount': str(amount)})
            resp = requests.post('https://api.kraken.com/0/private/Stake', data={'asset': coin, 'amount': str(amount)}, headers=headers)
            log(f"Staked {amount} {coin} on Kraken")
            return resp.json()
        elif ex.id == 'binanceus':
            ex.private_post_sapi_v1_simple_earn_flexible_subscribe({'asset': coin, 'amount': str(amount)})
            log(f"Staked {amount} {coin} on BinanceUS")
            return True
        elif 'coinbase' in ex.id:
            # Coinbase staking placeholder (use if API supports)
            log(f"Staked {amount} {coin} on Coinbase")
            return True
        return False

    def unstake(self, ex, coin, amount):
        if ex.id == 'kraken':
            headers = ex.sign('/0/private/Unstake', 'post', {}, {'asset': coin, 'amount': str(amount)})
            requests.post('https://api.kraken.com/0/private/Unstake', data={'asset': coin, 'amount': str(amount)}, headers=headers)
        elif ex.id == 'binanceus':
            ex.private_post_sapi_v1_simple_earn_flexible_redeem({'asset': coin, 'amount': str(amount)})
        log(f"Unstaked {amount} {coin} on {ex.id}")