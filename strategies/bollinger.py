"""
strategies/bollinger.py
-----------------------
Bollinger Band + RSI kombinasyon stratejisi.

Sinyal mantığı:
  BUY:  Kapanış fiyatı alt bandın ALTINA kapanıyor VE RSI < 40
  SELL: Kapanış fiyatı üst bandın ÜSTÜNE kapanıyor VE RSI > 60
  HOLD: Yukarıdaki koşullar sağlanmıyorsa

Kullanım:
    strategy = BollingerStrategy()
    signal = strategy.generate_signal(df)
"""

import logging

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class BollingerStrategy(BaseStrategy):
    """Bollinger Bands ve RSI kullanan mean-reversion stratejisi."""

    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_buy_threshold": 40,   # RSI bu değerin altındaysa al
        "rsi_sell_threshold": 60,  # RSI bu değerin üstündeyse sat
    }

    def __init__(self, params: dict = None):
        merged_params = {**self.DEFAULT_PARAMS, **(params or {})}
        super().__init__(name="Bollinger_RSI", params=merged_params)

    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> str:
        """
        Bollinger Band + RSI bazlı sinyal üretir.

        Args:
            df: OHLCV DataFrame
            symbol: Hisse sembolü (loglama için)

        Returns:
            str: "BUY", "SELL" veya "HOLD"
        """
        min_rows = self.params["bb_period"] + 10
        if not self._check_data(df, min_rows=min_rows):
            return self._emit_signal("HOLD", symbol, reason="Yetersiz veri")

        try:
            close = df["close"].astype(float)

            # ── Bollinger Bands Hesapla ────────────────────────────────────
            bb = ta.bbands(
                close,
                length=self.params["bb_period"],
                std=self.params["bb_std"],
            )

            # ── RSI Hesapla ────────────────────────────────────────────────
            rsi = ta.rsi(close, length=self.params["rsi_period"])

            if bb is None or rsi is None:
                return self._emit_signal("HOLD", symbol, reason="İndikatör hesaplanamadı")

            # Bollinger band sütun isimlerini al
            bb_cols = bb.columns.tolist()
            lower_col = [c for c in bb_cols if "BBL" in c][0]
            upper_col = [c for c in bb_cols if "BBU" in c][0]

            price_now = close.iloc[-1]
            lower_band = bb[lower_col].iloc[-1]
            upper_band = bb[upper_col].iloc[-1]
            rsi_now = rsi.iloc[-1]

            # ── BUY: Alt banda dokunuş veya %2 yakınlık + RSI < 40 ───────
            band_range = upper_band - lower_band
            near_lower = band_range > 0 and (price_now - lower_band) / band_range <= 0.02
            if (price_now <= lower_band or near_lower) and rsi_now < self.params["rsi_buy_threshold"]:
                reason = (
                    f"Fiyat={price_now:.4f} alt banda yakın (Alt={lower_band:.4f}, %2 eşik), "
                    f"RSI={rsi_now:.1f}"
                )
                return self._emit_signal("BUY", symbol, price_now, reason)

            # ── SELL: Üst bandın üstüne kapanış + RSI > 60 ────────────────
            if price_now > upper_band and rsi_now > self.params["rsi_sell_threshold"]:
                reason = (
                    f"Fiyat={price_now:.4f} > Üst Band={upper_band:.4f}, "
                    f"RSI={rsi_now:.1f}"
                )
                return self._emit_signal("SELL", symbol, price_now, reason)

            # ── HOLD ───────────────────────────────────────────────────────
            return self._emit_signal(
                "HOLD",
                symbol,
                price_now,
                f"Band içinde | Alt={lower_band:.4f}, Üst={upper_band:.4f}, RSI={rsi_now:.1f}",
            )

        except Exception as e:
            logger.error(f"[Bollinger] Sinyal hesaplama hatası: {e}")
            return self._emit_signal("HOLD", symbol, reason=f"Hata: {e}")
