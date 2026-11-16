"""
config.py - Configuration module for auto_trade MT5 Bot.
Designed for Exness Standard Account with $10.00 starting balance.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_JSON = PROJECT_ROOT / "account_credentials.json"

# Defaults used only until credentials are saved from the desktop app's UI.
DEFAULT_CREDENTIALS = {
    "login": 0,
    "password": "",
    "server": "Exness-MT5Real",
    "path": "",
    # Exness Standard uses the "m" suffix (XAUUSDm/BTCUSDm). The free
    # MetaQuotes-Demo server exposes the same symbols with no suffix.
    "symbol_suffix": "m",
}


def load_credentials_data() -> dict:
    """Loads account credentials saved by the desktop app (account_credentials.json)."""
    if CREDENTIALS_JSON.exists():
        try:
            with open(CREDENTIALS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "login": int(data.get("login", 0)),
                    "password": str(data.get("password", "")),
                    "server": str(data.get("server", DEFAULT_CREDENTIALS["server"])),
                    "path": str(data.get("path", "")),
                    "symbol_suffix": str(data.get("symbol_suffix", DEFAULT_CREDENTIALS["symbol_suffix"])),
                }
        except Exception:
            pass

    return dict(DEFAULT_CREDENTIALS)


@dataclass(frozen=True)
class SymbolConfig:
    """Per-symbol trading parameters."""
    symbol: str
    timeframe: str = "M5"  # 5-minute candles
    lot_size: float = 0.01  # Minimum lot size for Exness Standard
    stop_loss_points: int = 150  # Stop Loss in points (e.g., $1.50 on Gold at 0.01 point)
    take_profit_points: int = 300  # Take Profit in points (1:2 Risk/Reward ratio)
    max_spread_points: int = 50  # Max allowable spread in points before blocking entries
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    rsi_period: int = 14
    rsi_bullish_threshold: float = 50.0  # RSI must be > 50 for BUY
    rsi_bearish_threshold: float = 50.0  # RSI must be < 50 for SELL
    rsi_overbought_limit: float = 70.0  # Reject BUY if RSI >= 70
    rsi_oversold_limit: float = 30.0  # Reject SELL if RSI <= 30
    magic_number: int = 881001


@dataclass(frozen=True)
class AccountRiskConfig:
    """Account-wide risk limits strictly calibrated for a micro $10.00 balance."""
    # Global Single-Trade Lock: Only 1 position across ALL symbols at any time
    max_open_positions: int = 1

    # Daily USD Kill-Switch: If daily realized + floating loss hits $2.00, stop trading
    daily_loss_limit_usd: float = 2.00

    # Max margin usage percentage (used margin / equity * 100)
    max_margin_usage_pct: float = 60.0

    # Minimum free margin required to allow entering a new trade
    min_free_margin_usd: float = 2.50

    # Default order slippage in points
    slippage_points: int = 20

    # Main bot loop polling delay in seconds
    poll_interval_seconds: int = 5


@dataclass(frozen=True)
class MT5Credentials:
    """MT5 login credentials loaded from saved configuration or environment."""
    login: int = field(default_factory=lambda: load_credentials_data()["login"])
    password: str = field(default_factory=lambda: load_credentials_data()["password"])
    server: str = field(default_factory=lambda: load_credentials_data()["server"])
    path: str = field(default_factory=lambda: load_credentials_data()["path"])
    # "m" on Exness Standard (XAUUSDm/BTCUSDm); "" on MetaQuotes-Demo (XAUUSD/BTCUSD).
    symbol_suffix: str = field(default_factory=lambda: load_credentials_data()["symbol_suffix"])


def _build_symbol_configs(suffix: str) -> Dict[str, SymbolConfig]:
    """Builds per-symbol configs for the base Gold/BTC pair with the broker's symbol suffix."""
    gold_symbol = f"XAUUSD{suffix}"
    btc_symbol = f"BTCUSD{suffix}"
    return {
        # Gold:
        # Contract size: 100 oz. 0.01 lot = 1 oz.
        # 2 digits on Exness (point = 0.01): 150 points = $1.50 price delta = $1.50 PnL
        # Typical spread: 25-40 points
        gold_symbol: SymbolConfig(
            symbol=gold_symbol,
            timeframe="M5",
            lot_size=0.01,
            stop_loss_points=150,       # $1.50 SL on gold
            take_profit_points=300,      # $3.00 TP on gold (1:2 R:R)
            max_spread_points=45,        # 45 points ($0.45 spread ceiling)
            ema_fast_period=9,
            ema_slow_period=21,
            rsi_period=14,
            rsi_bullish_threshold=50.0,
            rsi_bearish_threshold=50.0,
            rsi_overbought_limit=70.0,
            rsi_oversold_limit=30.0,
            magic_number=881001
        ),

        # Bitcoin:
        # Contract size: 1 BTC. 0.01 lot = 0.01 BTC.
        # 2 digits on Exness (point = 0.01):
        # 15,000 points = $150.00 BTC price movement = $1.50 PnL on 0.01 lot
        # 30,000 points = $300.00 BTC price movement = $3.00 PnL on 0.01 lot (1:2 R:R)
        # Typical spread: 1500 - 3000 points ($15 - $30 spread)
        btc_symbol: SymbolConfig(
            symbol=btc_symbol,
            timeframe="M5",
            lot_size=0.01,
            stop_loss_points=15000,      # $150 BTC movement = $1.50 SL on 0.01 lot
            take_profit_points=30000,    # $300 BTC movement = $3.00 TP on 0.01 lot
            max_spread_points=3500,      # $35.00 max allowable spread
            ema_fast_period=9,
            ema_slow_period=21,
            rsi_period=14,
            rsi_bullish_threshold=50.0,
            rsi_bearish_threshold=50.0,
            rsi_overbought_limit=70.0,
            rsi_oversold_limit=30.0,
            magic_number=881002
        )
    }


ACCOUNT_RISK = AccountRiskConfig()
CREDENTIALS = MT5Credentials()

# Per-symbol configurations, keyed by symbol name (suffix depends on broker/server).
SYMBOL_CONFIGS: Dict[str, SymbolConfig] = _build_symbol_configs(CREDENTIALS.symbol_suffix)
