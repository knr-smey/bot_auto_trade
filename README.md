# auto_trade: Multi-Symbol MT5 Automated Trading Bot

A production-ready, multi-symbol automated trading bot for **MetaTrader 5 (MT5)**, specifically engineered to trade **Gold (`XAUUSDm`)** and **Bitcoin (`BTCUSDm`)** on an **Exness Standard Account** starting with a micro **$10.00 balance**.

---

## 1. Project Architecture & File Structure

```text
auto_trade/
├── .gitignore            # Git ignore for account_credentials.json, virtualenvs, logs, caches
├── requirements.txt      # MetaTrader5, pandas, numpy, customtkinter
├── README.md             # Setup, MT5 Market Watch configuration, and execution guide
├── ARCHITECTURE.md       # Diagrams of how the pieces connect and the trading loop
├── account_credentials.json  # Git-ignored; written by the GUI, read by config.py
├── src/
│   ├── config.py         # Per-symbol settings (XAUUSDm & BTCUSDm) and account risk limits
│   ├── strategy.py       # 9/21 EMA + 14 RSI signal generation on closed M5 candles
│   ├── risk_manager.py   # Global single-trade lock, per-symbol spread guard, margin check, and daily USD kill-switch
│   ├── bot.py            # Main execution loop, MT5 connection handler, and order router
│   ├── app.py            # Desktop GUI application for credentials & bot control
│   └── mock_mt5.py        # Drop-in MetaTrader5 API simulator for macOS/Linux paper trading
├── tests/
│   └── test_bot.py       # Automated offline test suite for strategy and risk guardrails
└── logs/
    └── auto_trade.log    # Rotating log file written by bot.py
```

---

## 2. Exness Standard Account Specifications ($10.00 Balance)

Trading with a **$10.00 starting balance** demands strict capital preservation and micro-lot sizing. Exness Standard accounts use the `m` suffix for retail symbols:

| Parameter | Gold (`XAUUSDm`) | Bitcoin (`BTCUSDm`) |
| :--- | :--- | :--- |
| **Contract Size** | 100 troy oz / lot | 1 BTC / lot |
| **Minimum Lot** | `0.01` lot (= 1 oz) | `0.01` lot (= 0.01 BTC) |
| **Point Value** | `0.01` ($0.01 / pt) | `0.01` ($0.01 / pt) |
| **Typical Spread** | 25 – 45 points | 1,500 – 3,000 points |
| **Stop Loss (SL)** | 150 points (~$1.50 risk) | 15,000 points (~$1.50 risk) |
| **Take Profit (TP)** | 300 points (~$3.00 reward, 1:2 R:R) | 30,000 points (~$3.00 reward, 1:2 R:R) |
| **Required Margin** | ~$1.30 (at 1:2000 leverage) | ~$2.25 – $4.50 (at 1:400/200 leverage) |

---

## 3. Strategy Logic (9/21 EMA + 14 RSI on M5)

The bot executes on **5-minute (M5) candles** and evaluates indicators **strictly on closed candles** (`bar[-2]` in MT5 rate buffer) to eliminate repainting:

### Buy Signal (Long)
1. **Golden Cross**: 9 EMA crosses above 21 EMA (`EMA9[-3] <= EMA21[-3]` and `EMA9[-2] > EMA21[-2]`).
2. **RSI Confirmation**: 14 RSI on the closed candle is in the bullish momentum zone:
   $$50 \le \text{RSI} < 70$$
   *(Prevents entering when market is already overbought).*

### Sell Signal (Short)
1. **Death Cross**: 9 EMA crosses below 21 EMA (`EMA9[-3] >= EMA21[-3]` and `EMA9[-2] < EMA21[-2]`).
2. **RSI Confirmation**: 14 RSI on the closed candle is in the bearish momentum zone:
   $$30 < \text{RSI} \le 50$$
   *(Prevents entering when market is already oversold).*

---

## 4. Multi-Layer Risk Guardrails (`risk_manager.py`)

1. **Global Single-Trade Lock**:
   - Only **1 active position** across all symbols is permitted at any given time.
   - On a $10 account, running concurrent Gold and BTC positions would over-leverage the balance and risk immediate stop-out.

2. **Daily USD Kill-Switch**:
   - Tracks cumulative daily realized PnL (including swap and commission) plus floating PnL.
   - If the account reaches a daily loss of **-$2.00** (20% of $10), the kill-switch triggers and halts all new order generation for the remainder of the day.

3. **Per-Symbol Spread Guard**:
   - Calculates real-time spread in points: `(ask - bid) / point`.
   - If spread exceeds the limit (e.g., 45 points on Gold or 3,500 points on BTC), new trades are rejected. Protects against news spikes, low-liquidity rollover, and high slippage.

4. **Pre-Trade Margin & Free Equity Check**:
   - Calls `mt5.order_calc_margin()` directly from the MT5 broker server before dispatching orders.
   - Verifies post-trade free margin remains above `$2.50` and total margin usage remains under `60%`.

5. **Dynamic Broker Filling Mode Detection**:
   - Inspects `symbol_info.filling_mode` to select `ORDER_FILLING_IOC`, `ORDER_FILLING_FOK`, or `ORDER_FILLING_RETURN`, preventing MT5 error 10030 (*Unsupported filling mode*).

---

## 5. Installation & Setup Guide

### Step 1: MT5 Terminal Configuration
1. Open your **MetaTrader 5 terminal** and log in to your **Exness Standard Account**.
2. Go to **Tools -> Options -> Expert Advisors**:
   - Check **"Allow algorithmic trading"**.
   - (Optional) Check "Allow WebRequest for listed URL" if needed.
3. Open the **Market Watch** window (`Ctrl+M`):
   - Right-click in Market Watch -> **Symbols** (`Ctrl+U`).
   - Search for `XAUUSDm` and click **Show Symbol**.
   - Search for `BTCUSDm` and click **Show Symbol**.

### Step 2: Python Environment Setup
Ensure Python 3.10+ is installed:

```bash
# Clone or navigate to the project directory
cd auto_trade

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux / macOS:
source venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

> [!NOTE]
> The official `MetaTrader5` package requires Windows (or a Windows VPS / Wine environment) to interact directly with the MT5 terminal IPC pipe.

### Step 3: Configure Credentials
There is no `.env` file to edit. Credentials are entered entirely through the
desktop app's UI and saved to `account_credentials.json` (git-ignored) when you
click **Save Account** — see Step 4 below.

---

## 6. Running the Application

### Option A: Modern Desktop GUI (Recommended)
You can launch the visual desktop application to manage credentials, test connections, and control the bot:

```bash
python src/app.py
```

Features included in the Desktop App:
- **Credentials Form**: Input and save Account ID (Login), Password (with show/hide eye toggle), Server (dropdown with Exness servers plus the free `MetaQuotes-Demo` test server), Symbol Suffix (auto-fills: `m` for Exness, blank for `MetaQuotes-Demo`), and optional Terminal Path (with file browser). Saving writes to `account_credentials.json` only — no `.env` file is used.
- **Test Connection**: Tests login, displays account name, server, balance, and trading permissions in real-time.
- **Bot Engine Controller**: Single-click `▶ START BOT` and `⏹ STOP BOT` buttons with live status badges.
- **Embedded Console**: Streams real-time color-coded logs directly inside the app window with auto-scroll.

> [!TIP]
> To test the bot risk-free before using a real Exness account, pick **MetaQuotes-Demo**
> from the Server dropdown. Get a free demo login/password in the MT5 terminal via
> **File → Open an Account → search "MetaQuotes" → MetaQuotes Software Corp. → Demo Account**.
> Its Gold/Bitcoin symbols are named `XAUUSD`/`BTCUSD` (no suffix), which the Symbol Suffix
> field auto-fills as blank when you select that server.

---

### Option B: Command-Line Interface (CLI)

Run the bot directly via terminal:

```bash
python src/bot.py
```

### Expected Startup Output
```text
2026-11-13 22:30:00 [INFO] [auto_trade] Connecting to MetaTrader 5...
2026-11-13 22:30:01 [INFO] [auto_trade] Logging into MT5 account 12345678 on server Exness-MT5Real...
2026-11-13 22:30:02 [INFO] [auto_trade] ✅ Login authorized successfully.
==================================================
Connected Account: 12345678 (Trader Name)
Server:            Exness-MT5Real
Currency / Balance: USD $10.00 | Equity: $10.00
Leverage:          1:2000
Trade Allowed:     True
==================================================
2026-11-13 22:30:02 [INFO] [auto_trade] ✅ Symbol 'XAUUSDm' ready | Digits: 2 | Point: 0.01 | Spread: 28.0 pts
2026-11-13 22:30:02 [INFO] [auto_trade] ✅ Symbol 'BTCUSDm' ready | Digits: 2 | Point: 0.01 | Spread: 1850.0 pts
2026-11-13 22:30:02 [INFO] [auto_trade] 🚀 auto_trade engine started successfully. Monitoring M5 candle closes...
```

### Graceful Termination
Press `Ctrl+C` in the terminal:
```text
2026-11-13 22:35:10 [INFO] [auto_trade] Signal 2 received. Stopping...
2026-11-13 22:35:10 [INFO] [auto_trade] Shutting down auto_trade bot...
2026-11-13 22:35:10 [INFO] [auto_trade] Bot stopped. Have a profitable day!
```

---

## 7. Logs & Observability

- Real-time events stream to **stdout**.
- Historical execution logs are stored in `logs/auto_trade.log` with automatic rotating backup (5 MB max per file, 5 backup archives retained).

---

## 8. Risk Warning

> [!WARNING]
> Trading Leveraged Financial Instruments such as Forex, Commodities (Gold), and Cryptocurrencies carries substantial risk of loss. Starting with a $10.00 account represents high relative risk. Always test with an **Exness MT5 Demo Account** first before deploying live capital.
