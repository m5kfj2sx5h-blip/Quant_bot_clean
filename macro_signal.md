# this is the current message in TradingView alert message:

{{strategy.order.alert_message}}


# this is the MACRO signal pinescript for review and context.
// @version=5
// --- FINAL SCRIPT [BTC/Gold Rotation] ---
strategy("FINAL SCRIPT [BTC/Gold Rotation]",
     overlay=true,
     initial_capital=5590, 
     default_qty_type=strategy.percent_of_equity,
     default_qty_value=100,
     process_orders_on_close=false)

// ==========================================
// 1. UI INPUTS
// ==========================================
grp_mode = "--- SCRIPT MODE ---"
script_mode = input.string("Backtest", "Mode", options=["Backtest", "Live Signals"], group=grp_mode)

string secret        = "eyJhbGciOiJIUzI1NiJ9.eyJzaWduYWxzX3NvdXJjZV9pZCI6OTkyNzh9.pZbJ75vmMaKfIa3NLAXmeSCrwejBCMFsxq6IoSDRI_0"
string bot_uuid      = "8beb646c-987e-46de-8d16-5a0748b0fdf5"
string exchange      = "KRAKEN"

grp_backtest = "Backtest Settings"
start_time = input.time(timestamp("01 Jan 2024 00:00 +0000"), "Backtest Start Date", group=grp_backtest)

grp_regime = "Regime Thresholds"
score_entry = input.int(3, "BTC Favorable Score", group=grp_regime)
score_exit  = input.int(1, "BTC Unfavorable Score", group=grp_regime)

grp_mvrv = "MVRV Circuit Breaker"
peak_level  = input.float(6.0, "MVRV Peak", group=grp_mvrv)
floor_level = input.float(2.0, "MVRV Floor", group=grp_mvrv)

grp_ma = "Trend Filters"
sma_fast_len = input.int(15, "BTC Fast SMA", group=grp_ma)
sma_slow_len = input.int(50, "BTC Slow SMA", group=grp_ma)

// ==========================================
// 2. DATA & SCORING
// ==========================================
[btc_usd_close, mvrv_z] = request.security("CRYPTOCAP:BTC", "W", [close, (close - ta.sma(close, 52)) / ta.stdev(close, 52)], lookahead=barmerge.lookahead_on)
fast_ma = ta.sma(btc_usd_close, sma_fast_len)
slow_ma = ta.sma(btc_usd_close, sma_slow_len)

int regime_score = 0
if btc_usd_close > fast_ma
    regime_score += 1
if btc_usd_close > slow_ma
    regime_score += 1
if mvrv_z > 2.0
    regime_score += 1
if mvrv_z > 4.0
    regime_score += 1

var bool bot_is_locked = false
if mvrv_z >= peak_level
    bot_is_locked := true
if mvrv_z <= floor_level
    bot_is_locked := false

// ==========================================
// 3. SIGNALS & DATE FILTER
// ==========================================
bool in_date_range = time >= start_time
bool is_backtest_mode = script_mode == "Backtest"

bool should_be_in_btc = (regime_score >= score_entry) and not bot_is_locked and in_date_range
bool should_be_in_gold = ((regime_score <= score_exit) or (mvrv_z >= peak_level)) and in_date_range

// ==========================================
// 4. 3COMMAS WEBHOOK MESSAGES (ISO TIMESTAMP FIX)
// ==========================================
string gold_ticker = "PAXGUSDT" 
string btc_ticker  = "BTCUSDT"

// This formats the time into: YYYY-MM-DDTHH:MM:SSZ
string t_iso = str.format("{0,date,yyyy-MM-dd}T{0,time,HH:mm:ss}Z", timenow)

string msg_exit_gold  = '{"secret":"' + secret + '","action":"exit_long","bot_uuid":"' + bot_uuid + '","max_lag":"300","timestamp":"' + t_iso + '","trigger_price":"' + str.tostring(close) + '","tv_exchange":"' + exchange + '","tv_instrument":"' + gold_ticker + '"}'
string msg_enter_btc  = '{"secret":"' + secret + '","action":"enter_long","bot_uuid":"' + bot_uuid + '","max_lag":"300","timestamp":"' + t_iso + '","trigger_price":"' + str.tostring(close) + '","tv_exchange":"' + exchange + '","tv_instrument":"' + btc_ticker + '"}'

string msg_exit_btc   = '{"secret":"' + secret + '","action":"exit_long","bot_uuid":"' + bot_uuid + '","max_lag":"300","timestamp":"' + t_iso + '","trigger_price":"' + str.tostring(close) + '","tv_exchange":"' + exchange + '","tv_instrument":"' + btc_ticker + '"}'
string msg_enter_gold = '{"secret":"' + secret + '","action":"enter_long","bot_uuid":"' + bot_uuid + '","max_lag":"300","timestamp":"' + t_iso + '","trigger_price":"' + str.tostring(close) + '","tv_exchange":"' + exchange + '","tv_instrument":"' + gold_ticker + '"}'

// Combined signals
string rotate_to_btc_signal = msg_exit_gold + '\n' + msg_enter_btc
string rotate_to_gold_signal = msg_exit_btc + '\n' + msg_enter_gold

// ==========================================
// 5. STRATEGY EXECUTION
// ==========================================
if is_backtest_mode
    if should_be_in_btc
        strategy.entry("BuyBTC", strategy.long)
    if should_be_in_gold
        strategy.close("BuyBTC", comment="SellBTC")
else
    var string last_position = "GOLD" 
    if should_be_in_btc and last_position == "GOLD"
        alert(rotate_to_btc_signal, alert.freq_once_per_bar)
        last_position := "BTC"
        label.new(bar_index, low, "ROTATE TO BTC", color=color.blue, style=label.style_label_up)
    if should_be_in_gold and last_position == "BTC"
        alert(rotate_to_gold_signal, alert.freq_once_per_bar)
        last_position := "GOLD"
        label.new(bar_index, high, "ROTATE TO GOLD", color=color.orange, style=label.style_label_down)