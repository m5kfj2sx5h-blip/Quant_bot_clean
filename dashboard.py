import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import ccxt
import os
import json
import time
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
import numpy as np

load_dotenv('/Users/dj3bosmacbookpro/Desktop/.env')

FEE_STATE_PATH = '/Users/dj3bosmacbookpro/Desktop/QUANT_bot/fee_state.json'

class FeeStateManager:
    def __init__(self):
        self.state = self._load_state()
        self._ensure_monthly_reset()
    
    def _load_state(self):
        default_state = {
            "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
            "exchanges": {
                "binance": {
                    "discount_active": True,
                    "discount_type": "BNB_PAYMENT",
                    "standard_taker": 0.001,
                    "discounted_taker": 0.00095,
                    "bnb_balance_check": True,
                    "notes": "BNB discount: ON. 5% savings active.",
                    "trades_with_discount": 0
                },
                "kraken": {
                    "discount_active": True,
                    "discount_type": "KRAKEN_PLUS",
                    "monthly_fee_credit_usd": 10000.0,
                    "fees_used_this_month_usd": 0.0,
                    "credit_remaining_usd": 10000.0,
                    "standard_taker": 0.0026,
                    "discounted_taker": 0.0,
                    "notes": "Kraken+ Active: $10k/month free fees."
                },
                "coinbase": {
                    "discount_active": True,
                    "discount_type": "COINBASE_ONE",
                    "monthly_fee_credit_usd": 500.0,
                    "fees_used_this_month_usd": 0.0,
                    "credit_remaining_usd": 500.0,
                    "standard_taker": 0.006,
                    "discounted_taker": 0.0,
                    "notes": "Coinbase One Active: $500/month free fees."
                }
            }
        }
        try:
            if os.path.exists(FEE_STATE_PATH):
                with open(FEE_STATE_PATH, 'r') as f:
                    return json.load(f)
        except:
            pass
        return default_state
    
    def _ensure_monthly_reset(self):
        current_date = datetime.now().strftime("%Y-%m-%d")
        last_reset = self.state.get("last_reset_date", current_date)
        if last_reset[:7] != current_date[:7]:
            for exch_data in self.state["exchanges"].values():
                if "fees_used_this_month_usd" in exch_data:
                    exch_data["fees_used_this_month_usd"] = 0.0
                if exch_data["discount_type"] == "KRAKEN_PLUS":
                    exch_data["credit_remaining_usd"] = 10000.0
                elif exch_data["discount_type"] == "COINBASE_ONE":
                    exch_data["credit_remaining_usd"] = 500.0
            self.state["last_reset_date"] = current_date
            self.save_state()
    
    def get_current_taker_fee(self, exchange_name, trade_value_usd=0):
        exch = self.state["exchanges"].get(exchange_name.lower())
        if not exch:
            return {"effective_fee_rate": 0.001, "discount_active": False}
        
        if exch['discount_active']:
            if exch['discount_type'] in ['KRAKEN_PLUS', 'COINBASE_ONE']:
                potential_fee = trade_value_usd * exch['discounted_taker']
                if potential_fee <= exch['credit_remaining_usd']:
                    return {
                        "effective_fee_rate": exch['discounted_taker'],
                        "discount_active": True,
                        "credit_remaining": exch['credit_remaining_usd']
                    }
            else:
                return {
                    "effective_fee_rate": exch['discounted_taker'],
                    "discount_active": True,
                    "credit_remaining": None
                }
        
        return {
            "effective_fee_rate": exch['standard_taker'],
            "discount_active": False,
            "credit_remaining": exch.get('credit_remaining_usd', 0)
        }
    
    def save_state(self):
        try:
            with open(FEE_STATE_PATH, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass

fee_manager = FeeStateManager()

# Professional CSS styling - Apple-like aesthetic
st.markdown("""
<style>
/* Main Layout */
.stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    color: #f0f0f0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
}

/* Headers - Much smaller and professional */
h1 {
    font-size: 1.8rem !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    margin-bottom: 0.5rem !important;
    background: linear-gradient(90deg, #ffffff 0%, #a5b4fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

h2, h3 {
    font-size: 1.1rem !important;
    font-weight: 500 !important;
    letter-spacing: -0.01em !important;
    opacity: 0.9;
    margin-top: 0.5rem !important;
    margin-bottom: 0.5rem !important;
}

/* Metric Cards - Professional */
.metric-card {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(20px);
    border-radius: 12px;
    padding: 1rem;
    border: 1px solid rgba(255, 255, 255, 0.08);
    margin-bottom: 0.75rem;
    height: 100%;
    transition: all 0.3s ease;
}

.metric-card:hover {
    border-color: rgba(255, 255, 255, 0.15);
    transform: translateY(-1px);
}

/* Exchange Cards with Logos */
.exchange-card {
    background: rgba(255, 255, 255, 0.07);
    border-radius: 12px;
    padding: 1rem;
    margin-bottom: 0.75rem;
    border-left: 4px solid;
    transition: all 0.3s ease;
}

.exchange-card:hover {
    background: rgba(255, 255, 255, 0.09);
    transform: translateY(-1px);
}

.exchange-online { border-left-color: #00ffa3; }
.exchange-offline { border-left-color: #ff4757; }

/* Status Indicators */
.status-online {
    color: #00ffa3;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.5px;
}

.status-offline {
    color: #ff4757;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.5px;
}

/* Compact labels */
.compact-label {
    font-size: 0.7rem !important;
    opacity: 0.6;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 0.25rem;
}

.compact-metric {
    font-size: 1.1rem !important;
    font-weight: 600;
    margin: 0.25rem 0;
}

/* Data Table Styling */
.dataframe {
    background: transparent !important;
    border: none !important;
}

.dataframe th {
    background: rgba(255, 255, 255, 0.05) !important;
    border: none !important;
    font-size: 0.75rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: rgba(255, 255, 255, 0.7) !important;
    padding: 0.5rem !important;
}

.dataframe td {
    border: none !important;
    font-size: 0.8rem !important;
    padding: 0.5rem !important;
    color: rgba(255, 255, 255, 0.9) !important;
}

/* Hide Streamlit elements */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.stDeployButton {display:none;}

/* Button Styling */
.stButton > button {
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%) !important;
    color: white !important;
    font-weight: 500 !important;
    font-size: 0.8rem !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 0.5rem 1rem !important;
    transition: all 0.3s ease !important;
}

.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3) !important;
}

/* Charts */
.plotly-chart {
    background: transparent !important;
}

/* Activity Log */
.activity-log {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    padding: 0.75rem;
    margin: 0.5rem 0;
    border-left: 3px solid #667eea;
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
}

/* Badges */
.intel-badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    border-radius: 10px;
    font-size: 0.65rem;
    font-weight: 500;
    margin: 0.1rem;
}
.badge-green { background: rgba(0, 255, 163, 0.15); color: #00ffa3; }
.badge-blue { background: rgba(102, 126, 234, 0.15); color: #667eea; }
.badge-yellow { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.badge-red { background: rgba(239, 68, 68, 0.15); color: #ef4444; }

/* Gold Battery */
.gold-battery {
    background: rgba(245, 158, 11, 0.2);
    height: 6px;
    border-radius: 3px;
    margin: 0.5rem 0;
    overflow: hidden;
}

.gold-battery-fill {
    background: linear-gradient(90deg, #fbbf24 0%, #f59e0b 100%);
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}
</style>
""", unsafe_allow_html=True)

@st.cache_resource(ttl=300)
def initialize_exchanges():
    exchanges = {}
    configs = {
        'kraken': {
            'class': ccxt.kraken,
            'key': os.getenv('KRAKEN_KEY'),
            'secret': os.getenv('KRAKEN_SECRET'),
            'color': '#5844a8',
            'logo': '₭'
        },
        'binance': {
            'class': ccxt.binanceus,
            'key': os.getenv('BINANCE_KEY'),
            'secret': os.getenv('BINANCE_SECRET'),
            'color': '#f0b90b',
            'logo': 'ⓑ'
        },
        'coinbase': {
            'class': ccxt.coinbaseadvanced,
            'key': os.getenv('COINBASE_KEY'),
            'secret': os.getenv('COINBASE_SECRET').replace('\\n', '\n') if os.getenv('COINBASE_SECRET') else '',
            'color': '#0052ff',
            'logo': 'Ⓒ'
        }
    }
    
    for name, config in configs.items():
        try:
            if not config['key'] or not config['secret']:
                exchanges[name] = {
                    'client': None,
                    'status': "OFFLINE",
                    'color': config['color'],
                    'logo': config['logo'],
                    'last_check': datetime.now()
                }
                continue

            exchange = config['class']({
                'apiKey': config['key'],
                'secret': config['secret'],
                'enableRateLimit': True,
            })

            exchange.fetch_time()
            exchanges[name] = {
                'client': exchange,
                'status': "ONLINE",
                'color': config['color'],
                'logo': config['logo'],
                'last_check': datetime.now()
            }
            
        except Exception as e:
            exchanges[name] = {
                'client': None,
                'status': f"ERROR: {str(e)[:30]}",
                'color': config['color'],
                'logo': config['logo'],
                'last_check': datetime.now()
            }
    
    return exchanges

@st.cache_data(ttl=10)
def fetch_exchange_balances():
    exchanges = initialize_exchanges()
    balance_data = []
    total_net_worth = 0
    arbitrage_capital = 0
    total_btc = 0
    total_gold = 0
    
    # Asset tracking for detailed breakdown
    asset_details = {
        'BTC': {'amount': 0, 'value': 0},
        'USDT': {'amount': 0, 'value': 0},
        'USDC': {'amount': 0, 'value': 0},
        'USD': {'amount': 0, 'value': 0},
        'PAXG': {'amount': 0, 'value': 0},
        'ETH': {'amount': 0, 'value': 0},
        'Other': {'amount': 0, 'value': 0}
    }
    
    for name, data in exchanges.items():
        if data['status'] != "ONLINE" or not data['client']:
            balance_data.append({
                'Exchange': name.upper(),
                'NetWorth': 0,
                'ArbitrageCapital': 0,
                'Status': data['status'],
                'Details': {},
                'BTC': 0,
                'Stablecoins': 0,
                'Color': data['color'],
                'Logo': data['logo']
            })
            continue

        try:
            client = data['client']
            balance = client.fetch_balance()
            
            symbol = 'BTC/USDT' if name == 'binance' else 'BTC/USD'
            ticker = client.fetch_ticker(symbol)
            btc_price = ticker['last']
            
            exchange_net_worth = 0
            exchange_arbitrage_capital = 0
            asset_details_exchange = {}
            btc_amount = 0
            gold_amount = 0
            stable_amount = 0
            
            for asset, amount in balance['total'].items():
                if amount > 0:
                    value = 0
                    
                    if asset in ['USD', 'USDT', 'USDC']:
                        value = amount
                        stable_amount += amount
                        asset_details[asset]['amount'] += amount
                        asset_details[asset]['value'] += value
                        if amount <= balance['free'].get(asset, 0):
                            exchange_arbitrage_capital += value
                        
                    elif asset == 'BTC':
                        value = amount * btc_price
                        btc_amount = amount
                        total_btc += amount
                        asset_details['BTC']['amount'] += amount
                        asset_details['BTC']['value'] += value
                        if amount <= balance['free'].get('BTC', 0):
                            exchange_arbitrage_capital += value
                        
                    elif asset == 'ETH':
                        try:
                            eth_price = client.fetch_ticker('ETH/USD')['last']
                            value = amount * eth_price
                        except:
                            value = amount * btc_price * 0.05
                        asset_details['ETH']['amount'] += amount
                        asset_details['ETH']['value'] += value
                        
                    elif asset == 'PAXG':
                        try:
                            paxg_price = client.fetch_ticker('PAXG/USD')['last']
                            value = amount * paxg_price
                            gold_amount = amount
                            total_gold += amount
                        except:
                            value = amount * btc_price
                            gold_amount = amount
                            total_gold += amount
                        asset_details['PAXG']['amount'] += amount
                        asset_details['PAXG']['value'] += value
                        
                    else:
                        # Estimate other assets at BTC price * 0.01
                        value = amount * btc_price * 0.01
                        asset_details['Other']['amount'] += amount
                        asset_details['Other']['value'] += value
                    
                    exchange_net_worth += value
                    asset_details_exchange[asset] = {
                        'amount': amount,
                        'value': value,
                        'free': balance['free'].get(asset, 0)
                    }
            
            total_net_worth += exchange_net_worth
            arbitrage_capital += exchange_arbitrage_capital
            
            balance_data.append({
                'Exchange': name.upper(),
                'NetWorth': exchange_net_worth,
                'ArbitrageCapital': exchange_arbitrage_capital,
                'Status': data['status'],
                'Details': asset_details_exchange,
                'BTC': btc_amount,
                'Stablecoins': stable_amount,
                'Color': data['color'],
                'Logo': data['logo']
            })
            
        except Exception as e:
            balance_data.append({
                'Exchange': name.upper(),
                'NetWorth': 0,
                'ArbitrageCapital': 0,
                'Status': f"ERROR: {str(e)[:20]}",
                'Details': {},
                'BTC': 0,
                'Stablecoins': 0,
                'Color': data['color'],
                'Logo': data['logo']
            })
    
    return balance_data, total_net_worth, arbitrage_capital, total_btc, total_gold, asset_details

@st.cache_data(ttl=5)
def fetch_realtime_prices():
    exchanges = initialize_exchanges()
    price_data = []
    
    for name, data in exchanges.items():
        if data['status'] != "ONLINE" or not data['client']:
            price_data.append({
                'exchange': name.upper(),
                'btc_price': 0,
                'latency_ms': 0,
                'status': data['status'],
                'bid': 0,
                'ask': 0,
                'color': data['color'],
                'logo': data['logo']
            })
            continue
        
        try:
            client = data['client']
            start_time = time.time()
            symbol = 'BTC/USDT' if name == 'binance' else 'BTC/USD'
            ticker = client.fetch_ticker(symbol)
            latency_ms = int((time.time() - start_time) * 1000)
            
            price_data.append({
                'exchange': name.upper(),
                'btc_price': ticker['last'],
                'latency_ms': latency_ms,
                'status': "ONLINE",
                'bid': ticker['bid'],
                'ask': ticker['ask'],
                'volume': ticker['quoteVolume'],
                'color': data['color'],
                'logo': data['logo']
            })
            
        except Exception as e:
            price_data.append({
                'exchange': name.upper(),
                'btc_price': 0,
                'latency_ms': 0,
                'status': f"ERROR: {str(e)[:20]}",
                'bid': 0,
                'ask': 0,
                'color': data['color'],
                'logo': data['logo']
            })
    
    return price_data

def get_recent_trades():
    try:
        history_path = '/Users/dj3bosmacbookpro/Desktop/QUANT_bot/trade_history.json'
        if os.path.exists(history_path):
            with open(history_path, 'r') as f:
                trades = json.load(f)
                return trades[-10:]  # Last 10 trades
    except:
        pass
    return []

def get_bot_activity():
    """Get latest bot activity from log file"""
    try:
        log_path = '/Users/dj3bosmacbookpro/Desktop/QUANT_bot/bot_log.log'
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                lines = f.readlines()
                # Get last 20 lines, filter for important events
                important_lines = []
                for line in lines[-20:]:
                    if any(keyword in line for keyword in ['ARBITRAGE', 'REBALANCE', 'ERROR', 'BOUGHT', 'SOLD', 'PROFIT']):
                        important_lines.append(line.strip())
                return important_lines[-5:] if important_lines else []
    except:
        pass
    return []

def calculate_arbitrage_opportunities(price_data):
    opportunities = []
    
    online_exchanges = [p for p in price_data if p['status'] == "ONLINE" and p['btc_price'] > 0]
    
    for i in range(len(online_exchanges)):
        for j in range(i + 1, len(online_exchanges)):
            ex1 = online_exchanges[i]
            ex2 = online_exchanges[j]
            
            # Calculate spread both ways
            spread1 = ex2['bid'] - ex1['ask']  # Buy on ex1, Sell on ex2
            spread2 = ex1['bid'] - ex2['ask']  # Buy on ex2, Sell on ex1
            
            best_spread = max(spread1, spread2)
            
            if best_spread > 0:
                if best_spread == spread1:
                    buy_ex = ex1['exchange']
                    sell_ex = ex2['exchange']
                    buy_price = ex1['ask']
                    sell_price = ex2['bid']
                    direction = f"{ex1['logo']} → {ex2['logo']}"
                else:
                    buy_ex = ex2['exchange']
                    sell_ex = ex1['exchange']
                    buy_price = ex2['ask']
                    sell_price = ex1['bid']
                    direction = f"{ex2['logo']} → {ex1['logo']}"
                
                spread_pct = (best_spread / buy_price) * 100
                
                # Calculate fees
                trade_size_usd = 10000.0
                buy_fee_info = fee_manager.get_current_taker_fee(buy_ex.lower(), trade_size_usd)
                sell_fee_info = fee_manager.get_current_taker_fee(sell_ex.lower(), trade_size_usd)
                
                total_fee_pct = buy_fee_info['effective_fee_rate'] + sell_fee_info['effective_fee_rate']
                net_profit_pct = spread_pct - total_fee_pct
                net_profit_usd = trade_size_usd * (net_profit_pct / 100)
                
                profitable = net_profit_pct > 0.05
                latency_diff = abs(ex1['latency_ms'] - ex2['latency_ms'])
                
                opportunities.append({
                    'EXCHANGE': direction,
                    'SPREAD': f"${best_spread:.2f}",
                    'SPREAD_PCT': f"{spread_pct:.2f}",
                    'NET_PROFIT': f"${net_profit_usd:.2f}",
                    'BUY_PRICE': f"${buy_price:.2f}",
                    'SELL_PRICE': f"${sell_price:.2f}",
                    'LATENCY': f"{latency_diff}ms",
                    'PROFITABLE': 'YES' if profitable else 'NO'
                })
    
    return sorted(opportunities, key=lambda x: float(x['NET_PROFIT'].replace('$', '')), reverse=True)

def get_macro_rebalance_status(balance_data, price_data):
    """Calculate macro rebalance status"""
    # Simplified logic - in production, use the actual rebalance_monitor logic
    status = {
        'status': 'BALANCED',
        'message': 'All exchanges within optimal operating ranges',
        'actions_needed': 0,
        'exchanges': []
    }
    
    for balance in balance_data:
        if balance['Status'] == 'ONLINE':
            btc_ratio = (balance['BTC'] * 90000) / balance['NetWorth'] if balance['NetWorth'] > 0 else 0
            stable_ratio = balance['Stablecoins'] / balance['NetWorth'] if balance['NetWorth'] > 0 else 0
            
            issues = []
            if btc_ratio < 0.1:  # Less than 10% BTC
                issues.append('Low BTC reserves')
            if stable_ratio < 0.1:  # Less than 10% stablecoins
                issues.append('Low liquidity')
            
            if issues:
                status['actions_needed'] += 1
                status['exchanges'].append({
                    'name': balance['Exchange'],
                    'issues': issues,
                    'btc': balance['BTC'],
                    'stablecoins': balance['Stablecoins']
                })
    
    if status['actions_needed'] > 0:
        status['status'] = 'REBALANCE_NEEDED'
        status['message'] = f'{status["actions_needed"]} exchange(s) need attention'
    
    return status

def create_asset_allocation_chart(asset_details):
    """Create donut chart for asset allocation"""
    labels = []
    values = []
    colors = []
    
    for asset, data in asset_details.items():
        if data['value'] > 100:  # Only show assets worth more than $100
            labels.append(asset)
            values.append(data['value'])
            if asset == 'BTC':
                colors.append('#f7931a')
            elif asset in ['USDT', 'USDC', 'USD']:
                colors.append('#26a17b')
            elif asset == 'PAXG':
                colors.append('#ffd700')
            elif asset == 'ETH':
                colors.append('#627eea')
            else:
                colors.append('#8a8a8a')
    
    if not values:
        return None
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=.7,
        marker=dict(colors=colors),
        textinfo='label+percent',
        textposition='outside',
        hoverinfo='label+value+percent'
    )])
    
    fig.update_layout(
        showlegend=False,
        margin=dict(t=0, b=0, l=0, r=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white', size=10)
    )
    
    return fig

def create_exchange_distribution_chart(balance_data, asset_type='BTC'):
    """Create donut chart for BTC or Stablecoins distribution across exchanges"""
    labels = []
    values = []
    colors = []
    
    for balance in balance_data:
        if balance['Status'] == 'ONLINE' and balance['NetWorth'] > 0:
            labels.append(balance['Exchange'])
            if asset_type == 'BTC':
                value = balance['BTC'] * 90000  # Approximate BTC value
                values.append(value)
            else:  # Stablecoins
                values.append(balance['Stablecoins'])
            colors.append(balance['Color'])
    
    if not values or sum(values) == 0:
        return None
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=.7,
        marker=dict(colors=colors),
        textinfo='label+percent',
        textposition='outside',
        hoverinfo='label+value+percent'
    )])
    
    fig.update_layout(
        showlegend=False,
        margin=dict(t=0, b=0, l=0, r=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white', size=10)
    )
    
    return fig

def create_exchange_card(exchange_name, exchange_price, exchange_balance, fee_info):
    """Create professional exchange card without emojis"""
    
    if not exchange_price:
        return f"""
        <div class="exchange-card" style="border-left-color: #ff4757;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <div style="font-size: 1.2rem; font-weight: 600;">{exchange_name}</div>
                </div>
                <div class="status-offline">OFFLINE</div>
            </div>
            <div style="font-size: 0.8rem; opacity: 0.5;">No data available</div>
        </div>
        """
    
    status_class = "status-online" if exchange_price['status'] == "ONLINE" else "status-offline"
    border_color = exchange_price.get('color', '#00ffa3')
    
    html_parts = []
    
    html_parts.append(f'<div class="exchange-card" style="border-left-color: {border_color};">')
    
    # Header with logo and status
    html_parts.append(f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">')
    html_parts.append(f'<div style="display: flex; align-items: center; gap: 0.5rem;">')
    html_parts.append(f'<div style="font-size: 1.1rem; font-weight: 600; color: {border_color};">{exchange_name}</div>')
    html_parts.append('</div>')
    html_parts.append(f'<div class="{status_class}">{exchange_price["status"].split(":")[0]}</div>')
    html_parts.append('</div>')
    
    # Price section
    html_parts.append(f'<div style="background: rgba(0, 255, 163, 0.08); padding: 0.75rem; border-radius: 8px; margin-bottom: 0.75rem;">')
    html_parts.append(f'<div style="font-size: 1.3rem; font-weight: 600; color: #00ffa3; text-align: center;">')
    html_parts.append(f'${exchange_price["btc_price"]:,.2f}')
    html_parts.append('</div>')
    html_parts.append(f'<div style="display: flex; justify-content: space-between; margin-top: 0.5rem; font-size: 0.75rem; opacity: 0.7;">')
    html_parts.append(f'<span>Bid: ${exchange_price["bid"]:,.2f}</span>')
    html_parts.append(f'<span>Ask: ${exchange_price["ask"]:,.2f}</span>')
    html_parts.append(f'<span>{exchange_price["latency_ms"]}ms</span>')
    html_parts.append('</div>')
    html_parts.append('</div>')
    
    # Fee information
    html_parts.append('<div style="margin-bottom: 0.75rem; font-size: 0.8rem;">')
    html_parts.append('<div style="opacity: 0.7; margin-bottom: 0.25rem;">Effective Fee</div>')
    html_parts.append(f'<div style="color: #00ffa3; font-weight: 500;">{fee_info["effective_fee_rate"]*100:.3f}%</div>')
    
    if fee_info.get('discount_active'):
        discount_type = fee_info.get('discount_type', '').replace('_', ' ')
        html_parts.append(f'<div style="margin-top: 0.25rem; color: #00ffa3; font-size: 0.7rem;">{discount_type} Active</div>')
    
    html_parts.append('</div>')
    
    # Balance information
    if exchange_balance and exchange_balance['NetWorth'] > 0:
        html_parts.append('<div style="border-top: 1px solid rgba(255,255,255,0.1); padding-top: 0.75rem; font-size: 0.8rem;">')
        html_parts.append(f'<div style="font-weight: 600; color: #00ffa3;">TOTAL</div>')
        html_parts.append(f'<div style="font-size: 1rem; font-weight: 600; margin: 0.25rem 0;">${exchange_balance["NetWorth"]:,.2f}</div>')
        html_parts.append(f'<div style="opacity: 0.8; font-size: 0.75rem;">')
        html_parts.append(f'BTC: {exchange_balance["BTC"]:.4f} (${exchange_balance["BTC"]*exchange_price["btc_price"]:,.0f})')
        html_parts.append('</div>')
        html_parts.append('</div>')
    
    html_parts.append('</div>')
    
    return ''.join(html_parts)

def main():
    st.set_page_config(
        page_title="Quant Trading Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Page Header - Much smaller
    col1, col2 = st.columns([5, 1])
    with col1:
        st.markdown("### QUANT TRADING DASHBOARD")
        st.caption("Zero-Fee Optimized Execution")
    
    with col2:
        if st.button("Refresh", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()
    
    st.divider()
    
    # Fetch all data
    price_data = fetch_realtime_prices()
    balance_data, total_net_worth, arbitrage_capital, total_btc, total_gold, asset_details = fetch_exchange_balances()
    arb_opportunities = calculate_arbitrage_opportunities(price_data)
    recent_trades = get_recent_trades()
    bot_activity = get_bot_activity()
    macro_status = get_macro_rebalance_status(balance_data, price_data)
    
    # SYSTEM OVERVIEW
    st.markdown("#### SYSTEM OVERVIEW")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        online_count = sum(1 for b in balance_data if b['Status'] == 'ONLINE')
        status_color = "#00ffa3" if online_count == 3 else "#f59e0b" if online_count > 0 else "#ff4757"
        status_text = "OPERATIONAL" if online_count == 3 else "PARTIAL" if online_count > 0 else "OFFLINE"
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="compact-label">SYSTEM STATUS</div>
            <div class="compact-metric" style="color: {status_color};">
                {status_text}
            </div>
            <div style="font-size: 0.7rem; margin-top: 0.5rem; opacity: 0.7;">
                {online_count}/3 Connected
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="compact-label">NET WORTH</div>
            <div class="compact-metric" style="color: #00ffa3; font-size: 1.2rem;">${total_net_worth:,.2f}</div>
            <div style="font-size: 0.8rem; margin-top: 0.25rem; opacity: 0.8;">
                Arbitrage Capital: ${arbitrage_capital:,.0f}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        account_text = ""
        for balance in balance_data:
            status_color = "#00ffa3" if balance['Status'] == 'ONLINE' else "#ff4757"
            account_text += f"""
            <div style='display: flex; justify-content: space-between; font-size: 0.75rem; margin: 0.1rem 0;'>
                <span style='color: {balance["Color"]};'>{balance['Logo']} {balance['Exchange']}:</span>
                <span>${balance['NetWorth']:,.0f}</span>
            </div>
            """
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="compact-label">ACCOUNT BALANCES</div>
            {account_text}
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        btc_value = total_btc * (price_data[0]['btc_price'] if price_data and price_data[0]['btc_price'] > 0 else 90000)
        gold_value = total_gold * 2000
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="compact-label">ASSETS</div>
            <div style="font-size: 0.8rem;">
                <div style="display: flex; justify-content: space-between; margin: 0.2rem 0;">
                    <span>BTC:</span>
                    <span style="color: #00ffa3;">{total_btc:.4f}</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin: 0.2rem 0;">
                    <span>Gold:</span>
                    <span style="color: #f59e0b;">{total_gold:.2f} oz</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # MARKET INTELLIGENCE LAYER
    st.markdown("#### MARKET INTELLIGENCE")
    
    intel_cols = st.columns(5)
    
    with intel_cols[0]:
        st.markdown(f"""
        <div class="metric-card" style="border-left: 3px solid #00ffa3;">
            <div class="compact-label">MARKET PHASE</div>
            <div class="compact-metric" style="color: #00ffa3;">ACCUMULATION</div>
            <div style="margin-top: 0.5rem;">
                <span class="intel-badge badge-green">Wyckoff Phase 1</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with intel_cols[1]:
        st.markdown(f"""
        <div class="metric-card" style="border-left: 3px solid #667eea;">
            <div class="compact-label">AUCTION STATE</div>
            <div class="compact-metric" style="color: #667eea;">ACCEPTING</div>
            <div style="margin-top: 0.5rem;">
                <span class="intel-badge badge-blue">Price + Volume ↑</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with intel_cols[2]:
        st.markdown(f"""
        <div class="metric-card" style="border-left: 3px solid #f59e0b;">
            <div class="compact-label">WHALE CONVICTION</div>
            <div class="compact-metric" style="color: #f59e0b;">HIGH</div>
            <div style="margin-top: 0.5rem;">
                <span class="intel-badge badge-yellow">3+ Large Buys</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with intel_cols[3]:
        macro_color = "#00ffa3" if macro_status['status'] == 'BALANCED' else "#f59e0b" if macro_status['status'] == 'REBALANCE_NEEDED' else "#ff4757"
        st.markdown(f"""
        <div class="metric-card" style="border-left: 3px solid {macro_color};">
            <div class="compact-label">MACRO STATUS</div>
            <div class="compact-metric" style="color: {macro_color};">{macro_status['status'].replace('_', ' ')}</div>
            <div style="margin-top: 0.5rem; font-size: 0.7rem; opacity: 0.8;">
                {macro_status['message']}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with intel_cols[4]:
        is_weekend = datetime.now().weekday() >= 5
        weekend_color = "#ef4444" if is_weekend else "#00ffa3"
        weekend_text = "ACTIVE" if is_weekend else "INACTIVE"
        st.markdown(f"""
        <div class="metric-card" style="border-left: 3px solid {weekend_color};">
            <div class="compact-label">WEEKEND MODE</div>
            <div class="compact-metric" style="color: {weekend_color};">{weekend_text}</div>
            <div style="margin-top: 0.5rem;">
                <span class="intel-badge badge-red">+0.03% Spread</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ARBITRAGE OPPORTUNITIES (Moved above exchange dashboards)
    st.markdown("#### ARBITRAGE OPPORTUNITIES")
    
    if arb_opportunities:
        df_opportunities = pd.DataFrame(arb_opportunities)
        
        def color_profitable(val):
            if 'YES' in str(val):
                return 'color: #00ffa3; font-weight: 500;'
            elif 'NO' in str(val):
                return 'color: #ff4757;'
            return ''
        
        display_columns = ['EXCHANGE', 'SPREAD', 'NET_PROFIT', 'BUY_PRICE', 'SELL_PRICE', 'LATENCY', 'PROFITABLE']
        df_display = df_opportunities[display_columns] if not df_opportunities.empty else pd.DataFrame()
        
        if not df_display.empty:
            styled_df = df_display.style.applymap(color_profitable, subset=['PROFITABLE'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
        else:
            st.info("No arbitrage opportunities above 0.05% net profit threshold.")
    else:
        st.info("No arbitrage opportunities available.")
    
    st.divider()
    
    # EXCHANGE DASHBOARDS
    st.markdown("#### EXCHANGE DASHBOARDS")
    
    exchange_cards = st.columns(3)
    
    for idx, exchange_name in enumerate(['KRAKEN', 'BINANCE', 'COINBASE']):
        with exchange_cards[idx]:
            exchange_price = next((p for p in price_data if p['exchange'] == exchange_name), None)
            exchange_balance = next((b for b in balance_data if b['Exchange'] == exchange_name), None)
            
            fee_info = fee_manager.get_current_taker_fee(exchange_name.lower(), 10000) if exchange_price else {}
            
            card_html = create_exchange_card(
                exchange_name, 
                exchange_price, 
                exchange_balance,
                fee_info
            )
            
            st.markdown(card_html, unsafe_allow_html=True)
    
    st.divider()
    
    # GOLD VAULT STRATEGY (Moved below exchange dashboards)
    st.markdown("#### GOLD VAULT STRATEGY")
    
    gold_cols = st.columns([2, 1])
    
    with gold_cols[0]:
        monthly_goal_oz = 0.5
        accumulated_oz = total_gold
        accumulated_value = accumulated_oz * 2000
        goal_percentage = min(100, (accumulated_oz / monthly_goal_oz) * 100)
        next_buy_target = 1000
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="compact-label">MONTHLY GOLD ACCUMULATION</div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin: 0.5rem 0;">
                <div style="font-size: 0.8rem; color: #f59e0b;">Goal: {monthly_goal_oz} oz</div>
                <div style="font-size: 0.8rem; color: #00ffa3;">{accumulated_oz:.2f} oz (${accumulated_value:,.0f})</div>
            </div>
            <div class="gold-battery">
                <div class="gold-battery-fill" style="width: {goal_percentage}%;"></div>
            </div>
            <div style="font-size: 0.7rem; text-align: center; color: #fbbf24; margin: 0.25rem 0;">
                {goal_percentage:.0f}% Complete
            </div>
            <div style="font-size: 0.7rem; margin-top: 0.5rem;">
                <div style="display: flex; justify-content: space-between;">
                    <span>Next Buy Target:</span>
                    <span style="color: #f59e0b;">${next_buy_target:,.0f}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with gold_cols[1]:
        fee_state = fee_manager.state
        coinbase_remaining = fee_state['exchanges']['coinbase']['credit_remaining_usd']
        kraken_remaining = fee_state['exchanges']['kraken']['credit_remaining_usd']
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="compact-label">ZERO-FEE TRACKING</div>
            <div style="font-size: 0.75rem; margin: 0.5rem 0;">
                <div style="display: flex; justify-content: space-between;">
                    <span>Coinbase One:</span>
                    <span style="color: #00ffa3;">${coinbase_remaining:,.0f} / $500</span>
                </div>
                <div style="background: rgba(255,255,255,0.1); height: 4px; border-radius: 2px; margin: 0.25rem 0;">
                    <div style="background: #00ffa3; width: {((500-coinbase_remaining)/500)*100}%; height: 100%; border-radius: 2px;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 0.5rem;">
                    <span>Kraken+:</span>
                    <span style="color: #00ffa3;">${kraken_remaining:,.0f} / $10,000</span>
                </div>
                <div style="background: rgba(255,255,255,0.1); height: 4px; border-radius: 2px; margin: 0.25rem 0;">
                    <div style="background: #00ffa3; width: {((10000-kraken_remaining)/10000)*100}%; height: 100%; border-radius: 2px;"></div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # STRATEGY CONTROLS SECTION (Renamed and redesigned)
    st.markdown("#### MACRO COMMAND CENTER")
    
    control_cols = st.columns([2, 1, 1])
    
    with control_cols[0]:
        # Display macro rebalance status and actions
        if macro_status['status'] == 'REBALANCE_NEEDED':
            st.markdown(f"""
            <div style="background: rgba(245, 158, 11, 0.1); padding: 1rem; border-radius: 8px; border-left: 4px solid #f59e0b;">
                <div style="font-size: 0.9rem; font-weight: 500; color: #f59e0b; margin-bottom: 0.5rem;">
                    Manual Intervention Required
                </div>
                <div style="font-size: 0.8rem; opacity: 0.9;">
                    {macro_status['message']}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            for exchange in macro_status['exchanges']:
                with st.expander(f"{exchange['name']} - {', '.join(exchange['issues'])}", expanded=False):
                    st.write(f"BTC: {exchange['btc']:.4f}")
                    st.write(f"Stablecoins: ${exchange['stablecoins']:,.2f}")
        else:
            st.markdown(f"""
            <div style="background: rgba(0, 255, 163, 0.1); padding: 1rem; border-radius: 8px; border-left: 4px solid #00ffa3;">
                <div style="font-size: 0.9rem; font-weight: 500; color: #00ffa3; margin-bottom: 0.5rem;">
                    System Balanced
                </div>
                <div style="font-size: 0.8rem; opacity: 0.9;">
                    All exchanges operating within optimal parameters
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    with control_cols[1]:
        if st.button("BTC MODE", use_container_width=True, type="primary"):
            try:
                with open('/Users/dj3bosmacbookpro/Desktop/QUANT_bot/current_mode.txt', 'w') as f:
                    f.write("BTC")
                st.success("Switched to BTC Mode")
                time.sleep(1)
                st.rerun()
            except:
                st.error("Failed to switch mode")
    
    with control_cols[2]:
        if st.button("GOLD MODE", use_container_width=True):
            try:
                with open('/Users/dj3bosmacbookpro/Desktop/QUANT_bot/current_mode.txt', 'w') as f:
                    f.write("GOLD")
                st.success("Switched to GOLD Mode")
                time.sleep(1)
                st.rerun()
            except:
                st.error("Failed to switch mode")
    
    st.divider()
    
    # ASSET VISUALIZATION SECTION
    st.markdown("#### ASSET VISUALIZATION")
    
    viz_cols = st.columns(3)
    
    with viz_cols[0]:
        # Total Asset Allocation
        fig1 = create_asset_allocation_chart(asset_details)
        if fig1:
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info("Insufficient asset data for visualization")
    
    with viz_cols[1]:
        # BTC Distribution
        fig2 = create_exchange_distribution_chart(balance_data, 'BTC')
        if fig2:
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No BTC distribution data")
    
    with viz_cols[2]:
        # Stablecoins Distribution
        fig3 = create_exchange_distribution_chart(balance_data, 'STABLE')
        if fig3:
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No stablecoin distribution data")
    
    st.divider()
    
    # ACTIVITY LOG SECTION
    st.markdown("#### BOT ACTIVITY LOG")
    
    # Display latest activity
    if bot_activity:
        for activity in bot_activity:
            # Parse and format activity
            if "ARBITRAGE" in activity:
                color = "#00ffa3"
                icon = "↗"
            elif "PROFIT" in activity:
                color = "#00ffa3"
                icon = "💰"
            elif "ERROR" in activity or "FAILED" in activity:
                color = "#ff4757"
                icon = "⚠"
            elif "REBALANCE" in activity:
                color = "#f59e0b"
                icon = "⚖"
            else:
                color = "#667eea"
                icon = "📝"
            
            # Clean up the log line
            clean_activity = activity.split(" - ")[-1] if " - " in activity else activity[-100:]
            
            st.markdown(f"""
            <div class="activity-log" style="border-left-color: {color};">
                <span style="color: {color}; margin-right: 0.5rem;">{icon}</span>
                <span style="font-size: 0.8rem;">{clean_activity}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No recent activity to display")
    
    # Footer
    st.caption(f"Last Update: {datetime.now().strftime('%H:%M:%S')} | Net Worth: ${total_net_worth:,.2f} | Arbitrage Capital: ${arbitrage_capital:,.0f}")

if __name__ == "__main__":
    main()