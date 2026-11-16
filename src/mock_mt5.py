"""
mock_mt5.py - High-fidelity mock of the MetaTrader 5 API for macOS / Linux paper trading.
Allows full end-to-end testing of the bot, GUI, strategy, and risk controls without a Windows VM.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import random
import time
from typing import Dict, List, Optional, Tuple
import numpy as np

# MT5 Constants
TIMEFRAME_M5 = 5
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
TRADE_ACTION_DEAL = 1
TRADE_RETCODE_DONE = 10009
ORDER_TIME_GTC = 0

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2


@dataclass
class AccountInfo:
    login: int = 12345678
    trade_mode: int = 0
    leverage: int = 2000
    limit_orders: int = 200
    margin_so_mode: int = 0
    trade_allowed: bool = True
    trade_expert: bool = True
    margin_mode: int = 0
    currency_digits: int = 2
    balance: float = 10.00
    credit: float = 0.00
    profit: float = 0.00
    equity: float = 10.00
    margin: float = 0.00
    margin_free: float = 10.00
    margin_level: float = 0.00
    margin_so_call: float = 60.0
    margin_so_so: float = 0.0
    margin_initial: float = 0.0
    margin_maintenance: float = 0.0
    fifo: bool = False
    currency: str = "USD"
    name: str = "Exness Trader (Mac Simulation)"
    server: str = "Exness-MT5Trial (Simulated)"
    company: str = "Exness Technologies Ltd"


@dataclass
class TerminalInfo:
    community_account: bool = False
    connected: bool = True
    dlls_allowed: bool = True
    trade_allowed: bool = True
    tradeapi_disabled: bool = False
    email_enabled: bool = False
    ftp_enabled: bool = False
    notifications_enabled: bool = False
    mqid: bool = False
    build: int = 4450
    maxbars: int = 100000
    codepage: int = 0
    ping_last: int = 15000
    community_balance: float = 0.0
    retransmission: float = 0.0
    company: str = "Exness"
    name: str = "MetaTrader 5"
    language: str = "English"
    path: str = "/Applications/MetaTrader 5.app"
    data_path: str = ""
    commondata_path: str = ""


@dataclass
class SymbolInfo:
    custom: bool = False
    chart_mode: int = 0
    select: bool = True
    visible: bool = True
    session_deals: int = 0
    session_buy_orders: int = 0
    session_sell_orders: int = 0
    volume: int = 0
    volumehigh: int = 0
    volumelow: int = 0
    time: int = 0
    digits: int = 2
    spread: int = 28
    spread_float: bool = True
    ticks_bookdepth: int = 10
    trade_calc_mode: int = 0
    trade_mode: int = 4
    start_time: int = 0
    expiration_time: int = 0
    trade_stops_level: int = 0
    trade_freeze_level: int = 0
    trade_exemode: int = 2
    swap_mode: int = 1
    swap_rollover3days: int = 3
    margin_hedged_use_checking: bool = False
    margin_hedged: float = 0.0
    margin_initial: float = 0.0
    margin_maintenance: float = 0.0
    trade_contract_size: float = 100.0
    point: float = 0.01
    bid: float = 2650.00
    bidhigh: float = 2655.00
    bidlow: float = 2645.00
    ask: float = 2650.28
    askhigh: float = 2655.28
    asklow: float = 2645.28
    last: float = 2650.14
    lasthigh: float = 2655.14
    lastlow: float = 2645.14
    volume_real: float = 0.0
    volumehigh_real: float = 0.0
    volumelow_real: float = 0.0
    option_strike: float = 0.0
    option_mode: int = 0
    option_right: int = 0
    currency_base: str = "XAU"
    currency_profit: str = "USD"
    currency_margin: str = "USD"
    bank: str = ""
    description: str = "Gold vs US Dollar"
    exchange: str = ""
    formula: str = ""
    isin: str = ""
    name: str = "XAUUSDm"
    page: str = ""
    path: str = "Forex\\XAUUSDm"
    filling_mode: int = SYMBOL_FILLING_IOC | SYMBOL_FILLING_FOK
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    volume_limit: float = 0.0


@dataclass
class Tick:
    time: int
    bid: float
    ask: float
    last: float
    volume: int
    time_msc: int
    flags: int
    volume_real: float


@dataclass
class Position:
    ticket: int
    time: int
    time_msc: int
    time_update: int
    time_update_msc: int
    type: int
    magic: int
    identifier: int
    reason: int
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    swap: float
    profit: float
    symbol: str
    comment: str
    external_id: str


@dataclass
class Deal:
    ticket: int
    order: int
    time: int
    time_msc: int
    type: int
    entry: int
    magic: int
    position_id: int
    reason: int
    volume: float
    price: float
    commission: float
    swap: float
    profit: float
    fee: float
    symbol: str
    comment: str
    external_id: str


@dataclass
class OrderResult:
    retcode: int
    deal: int
    order: int
    volume: float
    price: float
    bid: float
    ask: float
    comment: str
    request_id: int
    retcode_external: int


# Simulation State
_initialized = False
_account = AccountInfo()
_positions: Dict[int, Position] = {}
_deals: List[Deal] = []
_ticket_counter = 10001000

# Base prices for realistic simulation, keyed by the broker-agnostic root symbol
# (no suffix). Brokers append their own suffix (e.g. "m" on Exness, "" on
# MetaQuotes-Demo) which _resolve_base_symbol() strips before the lookup.
_base_prices = {
    "XAUUSD": {"price": 2650.00, "spread_pts": 28, "point": 0.01, "digits": 2, "contract": 100.0},
    "BTCUSD": {"price": 90500.00, "spread_pts": 2000, "point": 0.01, "digits": 2, "contract": 1.0}
}


def _resolve_base_symbol(symbol: str) -> Optional[str]:
    """Maps a broker-suffixed symbol (e.g. 'XAUUSDm', 'XAUUSD') to its root entry in _base_prices."""
    for base in _base_prices:
        if symbol.startswith(base):
            return base
    return None


def initialize(path: str = "") -> bool:
    global _initialized
    _initialized = True
    return True


def shutdown() -> None:
    global _initialized
    _initialized = False


def login(login: int, password: str = "", server: str = "", timeout: int = 5000) -> bool:
    global _account
    _account.login = login
    _account.server = server or "Exness-MT5Trial (Simulated)"
    return True


def last_error() -> Tuple[int, str]:
    return (1, "Success")


def account_info() -> Optional[AccountInfo]:
    global _account
    # Recalculate equity based on floating PnL
    floating = sum(p.profit for p in _positions.values())
    _account.profit = round(floating, 2)
    _account.equity = round(_account.balance + floating, 2)
    _account.margin_free = round(_account.equity - _account.margin, 2)
    return _account


def terminal_info() -> Optional[TerminalInfo]:
    return TerminalInfo()


def symbol_select(symbol: str, enable: bool) -> bool:
    return True


def symbol_info(symbol: str) -> Optional[SymbolInfo]:
    base = _resolve_base_symbol(symbol)
    if base is None:
        return None
    data = _base_prices[base]
    info = SymbolInfo(
        name=symbol,
        point=data["point"],
        digits=data["digits"],
        trade_contract_size=data["contract"],
        bid=data["price"],
        ask=data["price"] + (data["spread_pts"] * data["point"]),
        spread=data["spread_pts"]
    )
    return info


def symbol_info_tick(symbol: str) -> Optional[Tick]:
    base = _resolve_base_symbol(symbol)
    if base is None:
        return None
    data = _base_prices[base]

    # Subtle random walk price fluctuation
    delta = (random.random() - 0.49) * (data["point"] * 10)
    data["price"] = round(data["price"] + delta, data["digits"])

    bid = data["price"]
    ask = round(bid + (data["spread_pts"] * data["point"]), data["digits"])
    now_ts = int(time.time())

    return Tick(
        time=now_ts,
        bid=bid,
        ask=ask,
        last=bid,
        volume=10,
        time_msc=now_ts * 1000,
        flags=0,
        volume_real=1.0
    )


def copy_rates_from_pos(symbol: str, timeframe: int, start_pos: int, count: int) -> Optional[np.ndarray]:
    """Generates synthetic, deterministic M5 candles ending at the current time."""
    base = _resolve_base_symbol(symbol)
    if base is None:
        return None

    data = _base_prices[base]
    base_p = data["price"]
    now_ts = int(time.time())
    candle_sec = 300  # 5 minutes

    # Align to 5-minute boundaries
    current_candle_start = (now_ts // candle_sec) * candle_sec

    rates = []
    # Build 'count' candles back in time
    for i in range(count):
        idx = count - 1 - i
        candle_time = current_candle_start - (idx * candle_sec)

        # Generate a gentle cyclical trend so EMA crossovers occur naturally
        wave = np.sin((candle_time / 3600) * np.pi) * (data["point"] * 150)
        close_p = round(base_p + wave + ((random.random() - 0.5) * data["point"] * 20), data["digits"])
        open_p = round(close_p + ((random.random() - 0.5) * data["point"] * 10), data["digits"])
        high_p = round(max(open_p, close_p) + (random.random() * data["point"] * 15), data["digits"])
        low_p = round(min(open_p, close_p) - (random.random() * data["point"] * 15), data["digits"])

        rates.append((candle_time, open_p, high_p, low_p, close_p, 100, 28, 0))

    dtype = [
        ('time', '<i8'),
        ('open', '<f8'),
        ('high', '<f8'),
        ('low', '<f8'),
        ('close', '<f8'),
        ('tick_volume', '<u8'),
        ('spread', '<i4'),
        ('real_volume', '<u8')
    ]
    return np.array(rates, dtype=dtype)


def order_calc_margin(action: int, symbol: str, volume: float, price: float) -> Optional[float]:
    """Calculates required margin based on 1:2000 leverage."""
    base = _resolve_base_symbol(symbol)
    if base is None:
        return 1.50
    contract = _base_prices[base]["contract"]
    notional = price * volume * contract
    margin = notional / 2000.0
    return round(margin, 2)


def order_send(request: dict) -> Optional[OrderResult]:
    global _ticket_counter, _positions
    _ticket_counter += 1

    ticket = _ticket_counter
    pos = Position(
        ticket=ticket,
        time=int(time.time()),
        time_msc=int(time.time() * 1000),
        time_update=int(time.time()),
        time_update_msc=int(time.time() * 1000),
        type=request["type"],
        magic=request.get("magic", 0),
        identifier=ticket,
        reason=0,
        volume=request["volume"],
        price_open=request["price"],
        sl=request.get("sl", 0.0),
        tp=request.get("tp", 0.0),
        price_current=request["price"],
        swap=0.0,
        profit=0.0,
        symbol=request["symbol"],
        comment=request.get("comment", ""),
        external_id=""
    )
    _positions[ticket] = pos

    return OrderResult(
        retcode=TRADE_RETCODE_DONE,
        deal=ticket,
        order=ticket,
        volume=request["volume"],
        price=request["price"],
        bid=request["price"],
        ask=request["price"],
        comment="Request executed in Paper Simulation mode",
        request_id=1,
        retcode_external=0
    )


def positions_get(symbol: str = "") -> Optional[Tuple[Position, ...]]:
    if symbol:
        return tuple(p for p in _positions.values() if p.symbol == symbol)
    return tuple(_positions.values())


def history_deals_get(date_from: datetime, date_to: datetime) -> Optional[Tuple[Deal, ...]]:
    return tuple(_deals)
