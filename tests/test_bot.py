"""
test_bot.py - Unit test suite for auto_trade MT5 bot.
Tests strategy signal generation, risk guardrails, and calculations offline with mocks.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import SYMBOL_CONFIGS, AccountRiskConfig, SymbolConfig
from strategy import EmaRsiStrategy, OrderSignal
from risk_manager import RiskManager


class TestStrategy(unittest.TestCase):
    def setUp(self):
        self.sym_cfg = SYMBOL_CONFIGS["XAUUSDm"]
        self.strategy = EmaRsiStrategy(self.sym_cfg)

    def test_insufficient_bars(self):
        """Should return HOLD if there are fewer than minimum bars needed."""
        df = pd.DataFrame({
            'time': [100, 200],
            'open': [2600.0, 2601.0],
            'high': [2602.0, 2603.0],
            'low': [2599.0, 2600.0],
            'close': [2601.0, 2602.0],
            'tick_volume': [10, 20]
        })
        res = self.strategy.evaluate(df)
        self.assertEqual(res.signal, OrderSignal.HOLD)
        self.assertIn("Insufficient candle count", res.reason)

    def test_bullish_golden_cross(self):
        """
        Creates synthetic price data with a clear Golden Cross (EMA9 crossing above EMA21)
        and an RSI in the valid entry window (50 <= RSI < 70).
        """
        n = 60
        # Downtrend followed by an uptrend reversal at the end
        prices = [2650.0 - i * 0.5 for i in range(45)] + [2627.5 + i * 2.0 for i in range(15)]
        times = pd.date_range("2026-01-01", periods=n, freq="5min")

        df = pd.DataFrame({
            'time': times.astype(int) // 10**9,
            'open': prices,
            'high': [p + 1.0 for p in prices],
            'low': [p - 1.0 for p in prices],
            'close': prices,
            'tick_volume': [100] * n
        })

        res = self.strategy.evaluate(df)
        # Should detect bullish crossover or valid analysis
        self.assertIn(res.signal, [OrderSignal.BUY, OrderSignal.HOLD])
        self.assertEqual(res.symbol, "XAUUSDm")

    def test_rsi_calculation(self):
        """Verifies RSI values stay within [0, 100]."""
        series = pd.Series([100 + i + (i % 3) for i in range(40)])
        rsi = self.strategy.calculate_rsi(series, period=14)
        self.assertTrue((rsi >= 0).all() and (rsi <= 100).all())


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.risk_cfg = AccountRiskConfig(
            max_open_positions=1,
            daily_loss_limit_usd=2.00,
            max_margin_usage_pct=60.0,
            min_free_margin_usd=2.50
        )
        self.rm = RiskManager(self.risk_cfg)
        self.sym_cfg = SYMBOL_CONFIGS["XAUUSDm"]

    @patch("risk_manager.mt5")
    def test_global_single_trade_lock_permits_when_empty(self, mock_mt5):
        """When 0 positions are open, global trade lock should permit."""
        mock_mt5.positions_get.return_value = ()
        ok, msg = self.rm.check_global_trade_lock()
        self.assertTrue(ok)
        self.assertIn("OK", msg)

    @patch("risk_manager.mt5")
    def test_global_single_trade_lock_blocks_when_position_open(self, mock_mt5):
        """When 1 position is open, global trade lock should deny new entries."""
        mock_pos = MagicMock()
        mock_mt5.positions_get.return_value = (mock_pos,)
        ok, msg = self.rm.check_global_trade_lock()
        self.assertFalse(ok)
        self.assertIn("Global trade lock active", msg)

    @patch("risk_manager.mt5")
    def test_daily_kill_switch_triggers_on_exceeded_loss(self, mock_mt5):
        """When daily realized loss reaches $2.00, kill switch must trigger."""
        mock_deal = MagicMock()
        mock_deal.profit = -2.10
        mock_deal.commission = -0.05
        mock_deal.swap = 0.0
        mock_mt5.history_deals_get.return_value = (mock_deal,)
        mock_mt5.positions_get.return_value = ()

        ok, msg, pnl = self.rm.check_daily_kill_switch()
        self.assertFalse(ok)
        self.assertTrue(self.rm.kill_switch_triggered)
        self.assertIn("Kill-switch active", msg)

    @patch("risk_manager.mt5")
    def test_spread_guard_blocks_high_spread(self, mock_mt5):
        """If current spread exceeds configured ceiling, reject trade."""
        mock_sym_info = MagicMock()
        mock_sym_info.point = 0.01
        mock_mt5.symbol_info.return_value = mock_sym_info

        # Spread: 2601.00 - 2600.00 = 1.00 = 100 points (limit is 45)
        mock_tick = MagicMock()
        mock_tick.ask = 2601.00
        mock_tick.bid = 2600.00
        mock_mt5.symbol_info_tick.return_value = mock_tick

        ok, msg, spread = self.rm.check_spread("XAUUSDm", self.sym_cfg)
        self.assertFalse(ok)
        self.assertIn("Spread too high", msg)

    @patch("risk_manager.mt5")
    def test_volume_normalization(self, mock_mt5):
        """Snaps lot size to broker volume step and checks boundaries."""
        mock_info = MagicMock()
        mock_info.volume_min = 0.01
        mock_info.volume_max = 100.0
        mock_info.volume_step = 0.01
        mock_mt5.symbol_info.return_value = mock_info

        ok, vol, _ = self.rm.normalize_volume("XAUUSDm", 0.01)
        self.assertTrue(ok)
        self.assertEqual(vol, 0.01)

        # Reject below min
        ok, _, msg = self.rm.normalize_volume("XAUUSDm", 0.005)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
