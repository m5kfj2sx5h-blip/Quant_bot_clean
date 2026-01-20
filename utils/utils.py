import os
import time
from dotenv import load_dotenv
import ccxt

shared_state = {'mode': 'GOLD', 'pnl': 0, 'paxg_cold': 0, 'alerts': []}


def log(message):
    with open('logs/quant.log', 'a') as f:
        f.write(f"{time.ctime()}: {message}\n")
    shared_state['alerts'].append(message)


def load_config():
    load_dotenv('../config/.env')

    # Safe defaults if .env missing/empty
    min_profit = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.15'))
    max_trade_pct = float(os.getenv('MAX_TRADE_SIZE_PCT', '10'))
    gold_sweep_max = int(os.getenv('GOLD_SWEEP_MAX_PER_MONTH', '2'))
    paper_mode = os.getenv('PAPER_MODE', 'false').lower() == 'true'
    withdraw_enabled = os.getenv('WITHDRAW_ENABLED', 'false').lower() == 'true'
    transfer_stable = os.getenv('TRANSFER_STABLE', 'USDT')
    default_stake = os.getenv('DEFAULT_STAKE_COIN', 'ETH')
    webhook_pass = os.getenv('WEBHOOK_PASSPHRASE', 'secretphrase')
    a_bot_coins = os.getenv('A_BOT_COINS', 'BTC,ETH,SOL,ADA,DOT,LINK').split(',')
    cold_wallet = os.getenv('BASE_WALLET', '')

    return {
        'exchanges': {
            'kraken': ccxt.kraken({
                'apiKey': os.getenv('KRAKEN_KEY') or '',
                'secret': os.getenv('KRAKEN_SECRET') or '',
                'enableRateLimit': True,
            }),
            'binanceus': ccxt.binanceus({
                'apiKey': os.getenv('BINANCEUS_KEY') or '',
                'secret': os.getenv('BINANCEUS_SECRET') or '',
                'enableRateLimit': True,
            }),
            'coinbase': ccxt.coinbase({
                'apiKey': os.getenv('COINBASE_KEY') or '',
                'secret': os.getenv('COINBASE_SECRET') or '',
                'enableRateLimit': True,
            }),
            'coinbaseadv': ccxt.coinbase({  # Modern unified class
                'apiKey': os.getenv('COINBASEADV_KEY') or '',
                'secret': os.getenv('COINBASEADV_SECRET') or '',
                'password': os.getenv('COINBASEADV_PASSPHRASE') or '',  # If needed
                'enableRateLimit': True,
            }),
        },
        'cold_wallet': cold_wallet,
        'paper_mode': paper_mode,
        'min_profit': min_profit,
        'max_trade_pct': max_trade_pct,
        'default_stake': default_stake,
        'transfer_stable': transfer_stable,
        'withdraw_enabled': withdraw_enabled,
        'alert_email': os.getenv('ALERT_EMAIL', ''),
        'webhook_pass': webhook_pass,
        'gold_sweep_max': gold_sweep_max,
        'a_bot_coins': a_bot_coins,
    }