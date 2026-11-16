"""
strategy.py - EMA 9/21 Crossover + RSI 14 Strategy for M5 closed candles.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import pandas as pd
import numpy as np

from config import SymbolConfig


class OrderSignal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class SignalResult:
    signal: OrderSignal
    symbol: str
    candle_time: pd.Timestamp
    close_price: float
    ema_fast: float
    ema_slow: float
    rsi: float
    reason: str


class EmaRsiStrategy:
    """
    9/21 EMA + 14 RSI Momentum & Crossover Strategy.
    Crucial: Evaluates strictly on CLOSED candles to eliminate repainting.
    """

    def __init__(self, config: SymbolConfig):
        self.config = config

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average using standard ewm."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculate Relative Strength Index (RSI) using Wilder's smoothing technique.
        """
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        # Wilder's smoothing (alpha = 1 / period)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Takes raw OHLCV DataFrame and computes strategy indicators.
        DataFrame must contain ['time', 'open', 'high', 'low', 'close'].
        """
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df['time']):
            df['time'] = pd.to_datetime(df['time'], unit='s')

        df['ema_fast'] = self.calculate_ema(df['close'], self.config.ema_fast_period)
        df['ema_slow'] = self.calculate_ema(df['close'], self.config.ema_slow_period)
        df['rsi'] = self.calculate_rsi(df['close'], self.config.rsi_period)
        return df

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        """
        Evaluate signal on the most recently closed candle.
        
        Bar indices in dataframe:
        - df.iloc[-1]: Current open/live candle (still forming, do NOT use for trigger)
        - df.iloc[-2]: Most recently completed/closed candle (trigger bar)
        - df.iloc[-3]: Previous completed candle (pre-trigger bar for cross detection)
        """
        min_bars_needed = max(self.config.ema_slow_period, self.config.rsi_period) + 5
        if len(df) < min_bars_needed:
            return SignalResult(
                signal=OrderSignal.HOLD,
                symbol=self.config.symbol,
                candle_time=pd.Timestamp.now(),
                close_price=0.0,
                ema_fast=0.0,
                ema_slow=0.0,
                rsi=50.0,
                reason=f"Insufficient candle count ({len(df)} < {min_bars_needed})"
            )

        df = self.prepare_indicators(df)

        bar_pre = df.iloc[-3]   # 2 candles ago (completed)
        bar_last = df.iloc[-2]  # 1 candle ago (completed)

        candle_time = bar_last['time']
        close_price = float(bar_last['close'])
        ema_fast_pre = float(bar_pre['ema_fast'])
        ema_slow_pre = float(bar_pre['ema_slow'])
        ema_fast_last = float(bar_last['ema_fast'])
        ema_slow_last = float(bar_last['ema_slow'])
        rsi_last = float(bar_last['rsi'])

        # Crossover Detection
        bullish_crossover = (ema_fast_pre <= ema_slow_pre) and (ema_fast_last > ema_slow_last)
        bearish_crossover = (ema_fast_pre >= ema_slow_pre) and (ema_fast_last < ema_slow_last)

        # Bullish condition: Golden Cross + RSI confirming upward momentum without being overbought
        if bullish_crossover:
            if self.config.rsi_bullish_threshold <= rsi_last < self.config.rsi_overbought_limit:
                return SignalResult(
                    signal=OrderSignal.BUY,
                    symbol=self.config.symbol,
                    candle_time=candle_time,
                    close_price=close_price,
                    ema_fast=ema_fast_last,
                    ema_slow=ema_slow_last,
                    rsi=rsi_last,
                    reason=(f"Bullish EMA cross ({ema_fast_last:.3f} > {ema_slow_last:.3f}) "
                            f"with RSI {rsi_last:.1f} in [{self.config.rsi_bullish_threshold}, {self.config.rsi_overbought_limit})")
                )
            else:
                return SignalResult(
                    signal=OrderSignal.HOLD,
                    symbol=self.config.symbol,
                    candle_time=candle_time,
                    close_price=close_price,
                    ema_fast=ema_fast_last,
                    ema_slow=ema_slow_last,
                    rsi=rsi_last,
                    reason=f"Bullish EMA cross detected but RSI ({rsi_last:.1f}) outside valid entry range"
                )

        # Bearish condition: Death Cross + RSI confirming downward momentum without being oversold
        if bearish_crossover:
            if self.config.rsi_oversold_limit < rsi_last <= self.config.rsi_bearish_threshold:
                return SignalResult(
                    signal=OrderSignal.SELL,
                    symbol=self.config.symbol,
                    candle_time=candle_time,
                    close_price=close_price,
                    ema_fast=ema_fast_last,
                    ema_slow=ema_slow_last,
                    rsi=rsi_last,
                    reason=(f"Bearish EMA cross ({ema_fast_last:.3f} < {ema_slow_last:.3f}) "
                            f"with RSI {rsi_last:.1f} in ({self.config.rsi_oversold_limit}, {self.config.rsi_bearish_threshold}]")
                )
            else:
                return SignalResult(
                    signal=OrderSignal.HOLD,
                    symbol=self.config.symbol,
                    candle_time=candle_time,
                    close_price=close_price,
                    ema_fast=ema_fast_last,
                    ema_slow=ema_slow_last,
                    rsi=rsi_last,
                    reason=f"Bearish EMA cross detected but RSI ({rsi_last:.1f}) outside valid entry range"
                )

        return SignalResult(
            signal=OrderSignal.HOLD,
            symbol=self.config.symbol,
            candle_time=candle_time,
            close_price=close_price,
            ema_fast=ema_fast_last,
            ema_slow=ema_slow_last,
            rsi=rsi_last,
            reason=f"No crossover (Fast EMA={ema_fast_last:.3f}, Slow EMA={ema_slow_last:.3f}, RSI={rsi_last:.1f})"
        )
