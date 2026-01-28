from flask import Flask, render_template_string, request, redirect
import os
from dotenv import load_dotenv, set_key
from manager.persistence import PersistenceManager
from domain.entities import TradingMode

persistence_manager = PersistenceManager()

app = Flask(__name__)

# Casio UI with dynamic data, green-black style
casio_html = """
<!DOCTYPE html>
<html>
<head><title>QUANT-3.0 Casio</title>
<style>
body {font-family:monospace; background:black; color:lime;}
pre {border:2px solid lime; padding:10px;}
a {color:lime;}
.alert {color:red;}
</style></head>
<body>
<pre>
┌─ 🤖 QUANT-3.0 Casio ----------------------┐
│                                           │
│  [{{mode}}-MODE]                          │
│                                           │
│  Capital %                                │
│  Q-BOT  ▓▓▓▓ {{q_pct}} %   ▼              │
│  A-BOT  ▓ {{a_pct}} %     ▼               │
│  G-BOT  ▓ {{g_pct}} %     ▼               │
│  [Update]                                 │
│                                           │
│  Live P&L                                 │
│  Cycle Profit   ${{pnl}}                  │
│  PAXG Cold      {{paxg_cold}}             │
│  [Force 15 % Gold Sweep]                  │
│                                           │
│  [Download Full Log]   [Restart Bots]     │
│  [Settings]                               │
└-------------------------------------------┘
</pre>
{% for alert in alerts %}
<p class="alert">{{alert}}</p>
{% endfor %}
<a href="/settings">Settings</a> <a href="/sweep">Sweep</a> <a href="/log">Log</a> <a href="/restart">Restart</a>
</body></html>
"""

# Settings UI full form
settings_html = """
<!DOCTYPE html>
<html>
<head><title>Settings</title>
<style>body{background:black;color:lime;}</style></head>
<body>
<form method="POST">
    Kraken Key: <input name="KRAKEN_KEY" value="{{KRAKEN_KEY}}"><br>
    Kraken Secret: <input name="KRAKEN_SECRET" value="{{KRAKEN_SECRET}}"><br>
    BinanceUS Key: <input name="BINANCEUS_KEY" value="{{BINANCEUS_KEY}}"><br>
    BinanceUS Secret: <input name="BINANCEUS_SECRET" value="{{BINANCEUS_SECRET}}"><br>
    Coinbase Key: <input name="COINBASE_KEY" value="{{COINBASE_KEY}}"><br>
    Coinbase Secret: <input name="COINBASE_SECRET" value="{{COINBASE_SECRET}}"><br>
    CoinbaseAdv Key: <input name="COINBASEADV_KEY" value="{{COINBASEADV_KEY}}"><br>
    CoinbaseAdv Secret: <input name="COINBASEADV_SECRET" value="{{COINBASEADV_SECRET}}"><br>
    Base Wallet: <input name="BASE_WALLET" value="{{BASE_WALLET}}"><br>
    Paper Mode: <input name="PAPER_MODE" value="{{PAPER_MODE}}"><br>
    Min Profit Threshold: <input name="MIN_PROFIT_THRESHOLD" value="{{MIN_PROFIT_THRESHOLD}}"><br>
    Max Trade Size Pct: <input name="MAX_TRADE_SIZE_PCT" value="{{MAX_TRADE_SIZE_PCT}}"><br>
    Default Stake Coin: <input name="DEFAULT_STAKE_COIN" value="{{DEFAULT_STAKE_COIN}}"><br>
    Transfer Stable: <input name="TRANSFER_STABLE" value="{{TRANSFER_STABLE}}"><br>
    Withdraw Enabled: <input name="WITHDRAW_ENABLED" value="{{WITHDRAW_ENABLED}}"><br>
    Alert Email: <input name="ALERT_EMAIL" value="{{ALERT_EMAIL}}"><br>
    Webhook Passphrase: <input name="WEBHOOK_PASSPHRASE" value="{{WEBHOOK_PASSPHRASE}}"><br>
    Gold Sweep Max/Month: <input name="GOLD_SWEEP_MAX_PER_MONTH" value="{{GOLD_SWEEP_MAX_PER_MONTH}}"><br>
    A Bot Coins (comma sep): <input name="A_BOT_COINS" value="{{A_BOT_COINS}}"><br>
    <input type="submit" value="Save">
</form>
<a href="/">Back</a>
</body></html>
"""

@app.route('/')
def dashboard():
    last_state = persistence_manager.load_last_state() or {}
    mode = last_state.get('current_mode', 'BTC_MODE').upper().replace('_MODE', '')
    pnl = last_state.get('total_profit_usd', '0.00')
    paxg_cold = last_state.get('gold_accumulated_cycle', '0.00')
    
    q_pct = 85 if mode == 'BTC' else 15
    a_pct = 15 if mode == 'BTC' else 0
    g_pct = 0 if mode == 'BTC' else 85
    
    return render_template_string(casio_html, mode=mode, q_pct=q_pct, a_pct=a_pct, g_pct=g_pct, pnl=pnl, paxg_cold=paxg_cold, alerts=[])

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    load_dotenv('config/.env')
    if request.method == 'POST':
        for key, value in request.form.items():
            set_key('config/.env', key, value)
        return redirect('/')
    env = {k: os.getenv(k, '') for k in ['KRAKEN_KEY', 'KRAKEN_SECRET', 'BINANCEUS_KEY', 'BINANCEUS_SECRET', 'COINBASE_KEY', 'COINBASE_SECRET', 'COINBASEADV_KEY', 'COINBASEADV_SECRET', 'BASE_WALLET', 'PAPER_MODE', 'MIN_PROFIT_THRESHOLD', 'MAX_TRADE_SIZE_PCT', 'DEFAULT_STAKE_COIN', 'TRANSFER_STABLE', 'WITHDRAW_ENABLED', 'ALERT_EMAIL', 'WEBHOOK_PASSPHRASE', 'GOLD_SWEEP_MAX_PER_MONTH', 'A_BOT_COINS']}
    return render_template_string(settings_html, **env)

@app.route('/sweep')
def sweep():
    persistence_manager.save_command('G_SWEEP')
    return redirect('/')

@app.route('/restart')
def restart():
    os._exit(0)