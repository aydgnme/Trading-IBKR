"""
strategies/trend.py
-------------------
EMA trend takip stratejisi.

Trend tespiti:
  Yukarı trend: EMA20 > EMA50 > EMA200
  Aşağı trend:  EMA20 < EMA50 < EMA200

Giriş mantığı:
  BUY:  Yukarı trend VE 5m/15m timeframe'de pullback (fiyat EMA20'ye yakın)
  SELL: Aşağı trend VE 5m/15m timeframe'de pullback (fiyat EMA20'ye yakın)
  HOLD: Trend yok veya pullback koşulu sağlanmıyor

Scalping: 5m timeframe | Swing: 1h timeframe

Kullanım:
    strategy = TrendStrategy(timeframe="5m")  # scalping
    strategy = TrendStrategy(timeframe="1h")  # swing
"""

import logging

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class TrendStrategy(BaseStrategy):
    """EMA tabanlı trend takip ve pullback giriş stratejisi."""

    DEFAULT_PARAMS = {
        "ema_fast": 20,
        "ema_mid": 50,
        "ema_slow": 200,
        "pullback_pct": 0.02,   # EMA20'ye %2.0 yakınlık = pullback
        "timeframe": "1h",      # "5m" scalping, "1h" swing
    }

    def __init__(self, params: dict = None):
        merged_params = {**self.DEFAULT_PARAMS, **(params or {})}
        super().__init__(name="EMA_Trend", params=merged_params)

    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> str:
        """
        EMA trend + pullback bazlı sinyal üretir.

        Args:
            df: OHLCV DataFrame
            symbol: Hisse sembolü

        Returns:
            str: "BUY", "SELL" veya "HOLD"
        """
        min_rows = self.params["ema_slow"] + 10
        if not self._check_data(df, min_rows=min_rows):
            return self._emit_signal("HOLD", symbol, reason="Yetersiz veri (EMA200 için)")

        try:
            close = df["close"].astype(float)

            # ── EMA'ları Hesapla ───────────────────────────────────────────
            ema20 = ta.ema(close, length=self.params["ema_fast"]).iloc[-1]
            ema50 = ta.ema(close, length=self.params["ema_mid"]).iloc[-1]
            ema200 = ta.ema(close, length=self.params["ema_slow"]).iloc[-1]

            price_now = close.iloc[-1]

            # ── Trend Tespiti ──────────────────────────────────────────────
            uptrend = ema20 > ema50 > ema200
            downtrend = ema20 < ema50 < ema200

            # ── Pullback Tespiti ───────────────────────────────────────────
            # Fiyat EMA20'ye yakın mı? (pullback/retest bölgesi)
            distance_to_ema20 = abs(price_now - ema20) / ema20
            near_ema20 = distance_to_ema20 <= self.params["pullback_pct"]

            # ── BUY: Yukarı trend + EMA20'ye pullback ─────────────────────
            if uptrend and near_ema20 and price_now > ema20:
                reason = (
                    f"Yukarı trend (EMA20={ema20:.4f} > EMA50={ema50:.4f} > "
                    f"EMA200={ema200:.4f}), pullback={distance_to_ema20:.4%}"
                )
                return self._emit_signal("BUY", symbol, price_now, reason)

            # ── SELL: Aşağı trend + EMA20'ye pullback ─────────────────────
            if downtrend and near_ema20 and price_now < ema20:
                reason = (
                    f"Aşağı trend (EMA20={ema20:.4f} < EMA50={ema50:.4f} < "
                    f"EMA200={ema200:.4f}), pullback={distance_to_ema20:.4%}"
                )
                return self._emit_signal("SELL", symbol, price_now, reason)

            # ── HOLD ───────────────────────────────────────────────────────
            trend_str = "yukarı" if uptrend else ("aşağı" if downtrend else "yok")
            return self._emit_signal(
                "HOLD",
                symbol,
                price_now,
                f"Trend={trend_str}, EMA20 uzaklığı={distance_to_ema20:.4%}",
            )

        except Exception as e:
            logger.error(f"[EMA_Trend] Sinyal hesaplama hatası: {e}")
            return self._emit_signal("HOLD", symbol, reason=f"Hata: {e}")

    def get_trend_strength(self, df: pd.DataFrame) -> dict:
        """
        Trend gücünü hesaplar. Raporlama ve filtre için kullanılır.

        Returns:
            dict: trend yönü, EMA değerleri, güç skoru
        """
        if not self._check_data(df, min_rows=self.params["ema_slow"] + 10):
            return {"trend": "unknown"}

        close = df["close"].astype(float)
        ema20 = ta.ema(close, length=self.params["ema_fast"]).iloc[-1]
        ema50 = ta.ema(close, length=self.params["ema_mid"]).iloc[-1]
        ema200 = ta.ema(close, length=self.params["ema_slow"]).iloc[-1]

        if ema20 > ema50 > ema200:
            trend = "UP"
            strength = (ema20 - ema200) / ema200 * 100
        elif ema20 < ema50 < ema200:
            trend = "DOWN"
            strength = (ema200 - ema20) / ema200 * 100
        else:
            trend = "SIDEWAYS"
            strength = 0.0

        return {
            "trend": trend,
            "strength_pct": round(strength, 2),
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
        }
