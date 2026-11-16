"""
risk_manager.py - Capital preservation & risk controls for auto_trade MT5 Bot.
Calibrated for an Exness Standard Account starting with $10.00 balance.
"""

from datetime import datetime, time, timezone
import logging
from typing import Optional, Tuple

try:
    import MetaTrader5 as mt5
except ImportError:
    try:
        import mock_mt5 as mt5
    except ImportError:
        mt5 = None

from config import AccountRiskConfig, SymbolConfig


logger = logging.getLogger("auto_trade.risk")


class RiskManager:
    """
    Guards account capital with strict multi-layered checks:
    1. Global Single-Trade Lock (only 1 open position at a time across all symbols)
    2. Daily USD Kill-Switch (stops trading if daily loss hits threshold)
    3. Per-Symbol Spread Guard (protects against high spread spikes / news)
    4. Margin & Equity Pre-Trade Safety Check
    5. Lot Size Normalization against broker constraints
    """

    def __init__(self, risk_config: AccountRiskConfig):
        self.risk_config = risk_config
        self.kill_switch_triggered = False

    def check_global_trade_lock(self) -> Tuple[bool, str]:
        """
        Ensures that only up to max_open_positions (default 1) is active
        across the entire account. On a $10 balance, holding multiple positions
        can quickly lead to margin call or stop-out.
        """
        if mt5 is None:
            return False, "MT5 library is not loaded"

        positions = mt5.positions_get()
        if positions is None:
            return False, f"Failed to retrieve positions (error: {mt5.last_error()})"

        current_positions_count = len(positions)
        if current_positions_count >= self.risk_config.max_open_positions:
            return False, (f"Global trade lock active: {current_positions_count} open "
                           f"position(s) >= max allowable ({self.risk_config.max_open_positions})")

        return True, "Global trade lock OK"

    def check_daily_kill_switch(self) -> Tuple[bool, str, float]:
        """
        Calculates daily net PnL (realized deals closed today + current floating profit).
        If net daily loss exceeds daily_loss_limit_usd, locks trading for the day.
        """
        if mt5 is None:
            return False, "MT5 library is not loaded", 0.0

        # Start of today (00:00:00 UTC)
        now_utc = datetime.now(timezone.utc)
        start_of_day = datetime.combine(now_utc.date(), time.min, tzinfo=timezone.utc)

        # 1. Realized deals today
        history_deals = mt5.history_deals_get(start_of_day, now_utc)
        realized_pnl = 0.0
        if history_deals is not None and len(history_deals) > 0:
            for deal in history_deals:
                # Include profit, commission, and swap fees
                realized_pnl += (deal.profit + deal.commission + deal.swap)

        # 2. Floating PnL from active positions
        floating_pnl = 0.0
        positions = mt5.positions_get()
        if positions is not None and len(positions) > 0:
            for pos in positions:
                floating_pnl += (pos.profit + pos.swap)

        total_daily_pnl = realized_pnl + floating_pnl

        # Check breach
        if total_daily_pnl <= -abs(self.risk_config.daily_loss_limit_usd):
            if not self.kill_switch_triggered:
                logger.critical(
                    "🚨 DAILY KILL-SWITCH TRIGGERED! Net daily PnL: $%.2f "
                    "(Limit: -$%.2f). New trades permanently blocked today.",
                    total_daily_pnl, self.risk_config.daily_loss_limit_usd
                )
                self.kill_switch_triggered = True
            return False, f"Kill-switch active (Daily PnL: ${total_daily_pnl:.2f})", total_daily_pnl

        # Reset flag if account recovered above threshold
        if self.kill_switch_triggered and total_daily_pnl > -abs(self.risk_config.daily_loss_limit_usd):
            self.kill_switch_triggered = False

        return True, f"Daily PnL OK: ${total_daily_pnl:.2f}", total_daily_pnl

    def check_spread(self, symbol: str, sym_config: SymbolConfig) -> Tuple[bool, str, float]:
        """
        Verifies current live spread does not exceed maximum allowable spread points.
        Prevents entry during news events, market rollover, or liquidity voids.
        """
        if mt5 is None:
            return False, "MT5 library is not loaded", 0.0

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return False, f"Symbol {symbol} info not available", 0.0

        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.ask == 0 or tick.bid == 0:
            return False, f"Symbol {symbol} tick data unavailable", 0.0

        point = symbol_info.point
        if point <= 0:
            return False, f"Invalid symbol point value ({point})", 0.0

        spread_points = (tick.ask - tick.bid) / point

        if spread_points > sym_config.max_spread_points:
            return False, (f"Spread too high on {symbol}: {spread_points:.1f} points "
                           f"> max allowed {sym_config.max_spread_points} points"), spread_points

        return True, f"Spread OK ({spread_points:.1f} points)", spread_points

    def check_margin_and_balance(self, symbol: str, action: int, volume: float) -> Tuple[bool, str]:
        """
        Validates account free margin and equity before placing an order.
        Ensures the trade will not cause immediate stop-out on a $10 account.
        """
        if mt5 is None:
            return False, "MT5 library is not loaded"

        account = mt5.account_info()
        if account is None:
            return False, f"Failed to retrieve account info: {mt5.last_error()}"

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return False, f"Tick not available for {symbol}"

        order_price = tick.ask if action == mt5.ORDER_TYPE_BUY else tick.bid

        # Calculate required margin from MT5 server
        margin_required = mt5.order_calc_margin(action, symbol, volume, order_price)
        if margin_required is None:
            return False, f"Could not calculate required margin (error: {mt5.last_error()})"

        # 1. Balance/Equity check
        if account.equity < self.risk_config.min_free_margin_usd:
            return False, (f"Account equity (${account.equity:.2f}) is below minimum "
                           f"required threshold (${self.risk_config.min_free_margin_usd:.2f})")

        # 2. Post-trade Free margin check
        projected_free_margin = account.margin_free - margin_required
        if projected_free_margin < self.risk_config.min_free_margin_usd:
            return False, (f"Insufficient free margin. Free: ${account.margin_free:.2f}, "
                           f"Required: ${margin_required:.2f}, Post-trade: ${projected_free_margin:.2f} "
                           f"< buffer ${self.risk_config.min_free_margin_usd:.2f})")

        # 3. Margin usage check
        projected_margin_usage = ((account.margin + margin_required) / max(account.equity, 0.01)) * 100
        if projected_margin_usage > self.risk_config.max_margin_usage_pct:
            return False, (f"Projected margin usage ({projected_margin_usage:.1f}%) exceeds "
                           f"max allowed ({self.risk_config.max_margin_usage_pct:.1f}%)")

        return True, (f"Margin OK: Req=${margin_required:.2f}, Free=${account.margin_free:.2f}, "
                      f"Usage={projected_margin_usage:.1f}%")

    def normalize_volume(self, symbol: str, requested_volume: float) -> Tuple[bool, float, str]:
        """
        Validates and snaps lot size to broker's min, max, and step boundaries.
        """
        if mt5 is None:
            return False, requested_volume, "MT5 library is not loaded"

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            return False, requested_volume, f"Symbol {symbol} info not found"

        vol_min = sym_info.volume_min
        vol_max = sym_info.volume_max
        vol_step = sym_info.volume_step

        if requested_volume < vol_min:
            return False, vol_min, f"Requested lot {requested_volume} < broker minimum {vol_min}"

        if requested_volume > vol_max:
            return False, vol_max, f"Requested lot {requested_volume} > broker maximum {vol_max}"

        # Snap to nearest step
        steps = round((requested_volume - vol_min) / vol_step)
        normalized_volume = round(vol_min + (steps * vol_step), 2)

        return True, normalized_volume, "Volume valid"

    def pre_trade_approval(self, symbol: str, sym_config: SymbolConfig, action: int, volume: float) -> Tuple[bool, str]:
        """
        Composite pre-trade gatekeeper. Runs all checks in strict sequence.
        """
        # 1. Global Trade Lock
        ok, reason = self.check_global_trade_lock()
        if not ok:
            return False, reason

        # 2. Daily Kill-Switch
        ok, reason, _ = self.check_daily_kill_switch()
        if not ok:
            return False, reason

        # 3. Spread Guard
        ok, reason, _ = self.check_spread(symbol, sym_config)
        if not ok:
            return False, reason

        # 4. Volume Normalization
        ok, norm_vol, reason = self.normalize_volume(symbol, volume)
        if not ok:
            return False, reason

        # 5. Margin and Balance Safety
        ok, reason = self.check_margin_and_balance(symbol, action, norm_vol)
        if not ok:
            return False, reason

        return True, "Pre-trade risk checks passed"
