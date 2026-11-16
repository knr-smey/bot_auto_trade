"""
bot.py - Main multi-symbol execution loop, MT5 connection handler, and order router.
Designed for Exness Standard Account ($10.00 balance) trading XAUUSDm & BTCUSDm.
"""

from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import time
from typing import Dict, Optional

import pandas as pd

# Safe import for MT5 with automatic fallback to high-fidelity mock on macOS / Linux
try:
    import MetaTrader5 as mt5
    IS_SIMULATION = False
except ImportError:
    try:
        import mock_mt5 as mt5
        IS_SIMULATION = True
    except ImportError:
        mt5 = None
        IS_SIMULATION = False

from config import (
    ACCOUNT_RISK,
    CREDENTIALS,
    SYMBOL_CONFIGS,
    AccountRiskConfig,
    SymbolConfig,
)
from risk_manager import RiskManager
from strategy import EmaRsiStrategy, OrderSignal, SignalResult


def setup_logger() -> logging.Logger:
    """Configures console and rotating file logger."""
    os.makedirs("logs", exist_ok=True)
    log_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logger = logging.getLogger("auto_trade")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if re-initialized
    if logger.hasHandlers():
        logger.handlers.clear()

    # Console Handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(log_format)
    logger.addHandler(ch)

    # Rotating File Handler (5 MB per file, keep 5 backups)
    fh = RotatingFileHandler("logs/auto_trade.log", maxBytes=5 * 1024 * 1024, backupCount=5)
    fh.setLevel(logging.INFO)
    fh.setFormatter(log_format)
    logger.addHandler(fh)

    return logger


logger = setup_logger()


class AutoTradeBot:
    """
    Multi-symbol production automated trading bot for MetaTrader 5.
    Trades XAUUSDm (Gold) and BTCUSDm (Bitcoin) on M5 timeframe.
    """

    def __init__(self, risk_config: AccountRiskConfig = ACCOUNT_RISK):
        self.risk_config = risk_config
        self.risk_manager = RiskManager(risk_config)
        self.strategies: Dict[str, EmaRsiStrategy] = {
            sym: EmaRsiStrategy(cfg) for sym, cfg in SYMBOL_CONFIGS.items()
        }
        self.last_candle_time: Dict[str, int] = {sym: 0 for sym in SYMBOL_CONFIGS}
        self.is_running = False

    def connect_mt5(self) -> bool:
        """Initializes and logs into the MetaTrader 5 terminal."""
        if mt5 is None:
            logger.error(
                "❌ Neither MetaTrader5 nor mock_mt5 is available."
            )
            return False

        if IS_SIMULATION:
            logger.info("==================================================")
            logger.info("🎮 RUNNING IN SIMULATION & PAPER TRADING MODE (macOS)")
            logger.info("   Full engine: Live ticks, M5 closed bars, Risk Guard, and Orders.")
            logger.info("   (To connect to live Windows MT5 terminal, run on Windows or VPS)")
            logger.info("==================================================")
        else:
            logger.info("Connecting to MetaTrader 5 terminal...")

        # Initialize MT5
        init_kwargs = {}
        if CREDENTIALS.path.strip():
            init_kwargs["path"] = CREDENTIALS.path.strip()

        if not mt5.initialize(**init_kwargs):
            logger.error("❌ MT5 initialize() failed. Error code: %s", mt5.last_error())
            return False

        # Login if credentials are saved (account_credentials.json, via the desktop app)
        if CREDENTIALS.login > 0 and CREDENTIALS.password:
            logger.info("Logging into MT5 account %d on server %s...", CREDENTIALS.login, CREDENTIALS.server)
            authorized = mt5.login(
                login=CREDENTIALS.login,
                password=CREDENTIALS.password,
                server=CREDENTIALS.server
            )
            if not authorized:
                logger.error("❌ MT5 login failed. Error code: %s", mt5.last_error())
                mt5.shutdown()
                return False
            logger.info("✅ Login authorized successfully.")
        else:
            logger.info("No saved credentials found; attached to already active MT5 terminal session.")

        # Print terminal and account information
        terminal_info = mt5.terminal_info()
        account_info = mt5.account_info()

        if terminal_info is None or account_info is None:
            logger.error("❌ Unable to retrieve account/terminal details: %s", mt5.last_error())
            return False

        logger.info("==================================================")
        logger.info("Connected Account: %d (%s)", account_info.login, account_info.name)
        logger.info("Server:            %s", account_info.server)
        logger.info("Currency / Balance: %s $%.2f | Equity: $%.2f",
                    account_info.currency, account_info.balance, account_info.equity)
        logger.info("Leverage:          1:%d", account_info.leverage)
        logger.info("Trade Allowed:     %s", account_info.trade_allowed)
        logger.info("==================================================")

        if not account_info.trade_allowed:
            logger.warning("⚠️ Trade is NOT allowed on this account! Please enable Algo Trading in MT5.")

        return True

    def setup_symbols(self) -> bool:
        """Verifies symbol availability and enables them in Market Watch."""
        for symbol, cfg in SYMBOL_CONFIGS.items():
            sym_info = mt5.symbol_info(symbol)
            if sym_info is None:
                logger.error("❌ Symbol '%s' not found on server! Please check Exness account type or suffix.", symbol)
                return False

            if not sym_info.visible:
                logger.info("Enabling '%s' in Market Watch...", symbol)
                if not mt5.symbol_select(symbol, True):
                    logger.error("❌ Failed to enable '%s' in Market Watch: %s", symbol, mt5.last_error())
                    return False

            tick = mt5.symbol_info_tick(symbol)
            spread_points = ((tick.ask - tick.bid) / sym_info.point) if (tick and sym_info.point > 0) else 0
            logger.info(
                "✅ Symbol '%s' ready | Digits: %d | Point: %s | Contract: %s | Spread: %.1f pts",
                symbol, sym_info.digits, sym_info.point, sym_info.trade_contract_size, spread_points
            )
        return True

    @staticmethod
    def get_supported_filling_mode(symbol_info) -> int:
        """
        Determines the execution filling mode accepted by the broker for this symbol.
        Prevents MT5 error 10030 (Unsupported filling mode) common on Exness.
        """
        filling_mode = symbol_info.filling_mode
        if filling_mode & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        elif filling_mode & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def fetch_closed_candles(self, symbol: str, count: int = 100) -> Optional[pd.DataFrame]:
        """
        Fetches M5 candle rates from MT5.
        Pos 0 is the currently forming candle, pos 1 is the last completed candle.
        """
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, count)
        if rates is None or len(rates) == 0:
            logger.warning("No candle data received for %s (error: %s)", symbol, mt5.last_error())
            return None

        df = pd.DataFrame(rates)
        return df

    def execute_trade(self, symbol: str, signal_res: SignalResult) -> bool:
        """
        Pre-checks risk constraints and routes order to MT5.
        """
        sym_config = SYMBOL_CONFIGS[symbol]
        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            logger.error("Cannot execute trade: symbol %s info unavailable", symbol)
            return False

        action = mt5.ORDER_TYPE_BUY if signal_res.signal == OrderSignal.BUY else mt5.ORDER_TYPE_SELL

        # 1. Pre-trade Risk Guard Approval
        approved, reason = self.risk_manager.pre_trade_approval(
            symbol=symbol,
            sym_config=sym_config,
            action=action,
            volume=sym_config.lot_size
        )
        if not approved:
            logger.warning("⛔ Trade REJECTED by Risk Manager [%s]: %s", symbol, reason)
            return False

        # 2. Get latest tick for fresh entry price
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error("Cannot execute trade: live tick for %s unavailable", symbol)
            return False

        point = sym_info.point
        digits = sym_info.digits

        if signal_res.signal == OrderSignal.BUY:
            price = tick.ask
            sl = round(price - (sym_config.stop_loss_points * point), digits)
            tp = round(price + (sym_config.take_profit_points * point), digits)
            order_type = mt5.ORDER_TYPE_BUY
        else:
            price = tick.bid
            sl = round(price + (sym_config.stop_loss_points * point), digits)
            tp = round(price - (sym_config.take_profit_points * point), digits)
            order_type = mt5.ORDER_TYPE_SELL

        filling_mode = self.get_supported_filling_mode(sym_info)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": sym_config.lot_size,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": self.risk_config.slippage_points,
            "magic": sym_config.magic_number,
            "comment": f"auto_trade {signal_res.signal.value}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        logger.info(
            "🚀 Sending %s order for %s: Vol=%.2f, Price=%.*f, SL=%.*f, TP=%.*f",
            signal_res.signal.value, symbol, sym_config.lot_size, digits, price, digits, sl, digits, tp
        )

        result = mt5.order_send(request)
        if result is None:
            logger.error("❌ Order send returned None for %s (error: %s)", symbol, mt5.last_error())
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                "❌ Order rejected! Retcode: %d (%s), Comment: %s",
                result.retcode, result.comment, result.comment
            )
            return False

        logger.info(
            "🎉 ORDER EXECUTED SUCCESSFULLY! Ticket: %d | Symbol: %s | Price: %.*f | Vol: %.2f",
            result.order, symbol, digits, result.price, result.volume
        )
        return True

    def check_symbol_signals(self, symbol: str):
        """
        Checks for newly closed M5 candle on symbol and evaluates strategy signals.
        """
        df = self.fetch_closed_candles(symbol, count=100)
        if df is None or len(df) < 5:
            return

        # df.iloc[-1] is open bar; df.iloc[-2] is the most recently closed bar
        closed_bar = df.iloc[-2]
        closed_time = int(closed_bar['time'])

        # Check if we have already evaluated this candle close
        if closed_time <= self.last_candle_time[symbol]:
            return

        # New candle closed
        self.last_candle_time[symbol] = closed_time
        strategy = self.strategies[symbol]
        signal_res = strategy.evaluate(df)

        logger.info(
            "📊 [%s M5 Bar Closed %s] Close: %.2f | EMA9: %.3f | EMA21: %.3f | RSI: %.1f -> %s (%s)",
            symbol,
            signal_res.candle_time.strftime("%H:%M:%S"),
            signal_res.close_price,
            signal_res.ema_fast,
            signal_res.ema_slow,
            signal_res.rsi,
            signal_res.signal.value,
            signal_res.reason
        )

        if signal_res.signal in (OrderSignal.BUY, OrderSignal.SELL):
            self.execute_trade(symbol, signal_res)

    def log_account_status(self):
        """Prints open positions and daily health metrics."""
        account = mt5.account_info()
        if account is None:
            return

        _, _, daily_pnl = self.risk_manager.check_daily_kill_switch()
        positions = mt5.positions_get()
        open_count = len(positions) if positions is not None else 0

        logger.info(
            "💼 Account Status -> Balance: $%.2f | Equity: $%.2f | Open Positions: %d | Today PnL: $%.2f",
            account.balance, account.equity, open_count, daily_pnl
        )

        if positions and len(positions) > 0:
            for p in positions:
                ptype = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                logger.info(
                    "   ↳ #%d %s %s %.2f @ %.2f -> Current: %.2f | PnL: $%.2f | SL: %.2f | TP: %.2f",
                    p.ticket, p.symbol, ptype, p.volume, p.price_open, p.price_current, p.profit, p.sl, p.tp
                )

    def run(self):
        """Main bot execution loop."""
        if not self.connect_mt5():
            logger.error("Failed to establish MT5 connection. Exiting bot.")
            return

        if not self.setup_symbols():
            logger.error("Failed to verify trading symbols. Exiting bot.")
            mt5.shutdown()
            return

        self.is_running = True
        logger.info("🚀 auto_trade engine started successfully. Monitoring M5 candle closes...")

        status_counter = 0
        try:
            while self.is_running:
                # 1. Check daily kill-switch status
                kill_ok, kill_msg, _ = self.risk_manager.check_daily_kill_switch()
                if not kill_ok:
                    logger.warning("Kill switch active: %s. Pausing order generation.", kill_msg)

                # 2. Iterate each configured symbol
                for symbol in SYMBOL_CONFIGS:
                    try:
                        self.check_symbol_signals(symbol)
                    except Exception as e:
                        logger.error("Error processing symbol %s: %s", symbol, e, exc_info=True)

                # 3. Periodic account status log (every ~60 seconds)
                status_counter += self.risk_config.poll_interval_seconds
                if status_counter >= 60:
                    self.log_account_status()
                    status_counter = 0

                time.sleep(self.risk_config.poll_interval_seconds)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received.")
        finally:
            self.shutdown()

    def shutdown(self):
        """Gracefully terminates bot and frees MT5 resources."""
        self.is_running = False
        logger.info("Shutting down auto_trade bot...")
        if mt5 is not None:
            mt5.shutdown()
        logger.info("Bot stopped. Have a profitable day!")


def handle_signals(bot_instance: AutoTradeBot):
    """Registers POSIX signals for clean shutdown."""
    def _signal_handler(sig, frame):
        logger.info("Signal %s received. Stopping...", sig)
        bot_instance.is_running = False

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


if __name__ == "__main__":
    bot = AutoTradeBot()
    handle_signals(bot)
    bot.run()
