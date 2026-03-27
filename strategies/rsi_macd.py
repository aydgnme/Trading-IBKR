"""
strategies/rsi_macd.py
----------------------
RSI + MACD kombinasyon stratejisi.

Sinyal mantığı:
  BUY:  RSI < 35 VE MACD bullish crossover (MACD, sinyal çizgisini yukarı keser)
  SELL: RSI > 65 VE MACD bearish crossover (MACD, sinyal çizgisini aşağı keser)
  HOLD: Yukarıdaki koşullar sağlanmıyorsa

Kullanım:
    strategy = RSIMACDStrategy()
    signal = strategy.generate_signal(df)
"""

import logging

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class RSIMACDStrategy(BaseStrategy):
    """RSI ve MACD göstergelerini birleştiren strateji."""

    # Varsayılan parametreler
    DEFAULT_PARAMS = {
        "rsi_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "rsi_oversold": 45,    # Aşırı satım seviyesi
        "rsi_overbought": 55,  # Aşırı alım seviyesi
    }

    def __init__(self, params: dict = None):
        merged_params = {**self.DEFAULT_PARAMS, **(params or {})}
        super().__init__(name="RSI_MACD", params=merged_params)

    def _validate_params(self):
        """Parametre değerlerini doğrula."""
        # Temel doğrulama (params henüz set edilmemiş olabilir, güvenli kontrol)
        if not self.params:
            return
        rsi_p = self.params.get("rsi_period", 14)
        if rsi_p < 2:
            raise ValueError("rsi_period en az 2 olmalı.")

    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> str:
        """
        RSI + MACD bazlı sinyal üretir.

        Args:
            df: OHLCV DataFrame
            symbol: Hisse sembolü (loglama için)

        Returns:
            str: "BUY", "SELL" veya "HOLD"
        """
        min_rows = self.params["macd_slow"] + self.params["macd_signal"] + 10
        if not self._check_data(df, min_rows=min_rows):
            return self._emit_signal("HOLD", symbol, reason="Yetersiz veri")

        try:
            close = df["close"].astype(float)

            # ── RSI Hesapla ────────────────────────────────────────────────
            rsi = ta.rsi(close, length=self.params["rsi_period"])

            # ── MACD Hesapla ───────────────────────────────────────────────
            macd_df = ta.macd(
                close,
                fast=self.params["macd_fast"],
                slow=self.params["macd_slow"],
                signal=self.params["macd_signal"],
            )

            if rsi is None or macd_df is None:
                return self._emit_signal("HOLD", symbol, reason="İndikatör hesaplanamadı")

            # Son 2 mum için değerler (crossover tespiti için)
            rsi_now = rsi.iloc[-1]
            macd_line = macd_df.iloc[:, 0]    # MACD çizgisi
            signal_line = macd_df.iloc[:, 2]  # Sinyal çizgisi

            macd_now = macd_line.iloc[-1]
            macd_prev = macd_line.iloc[-2]
            sig_now = signal_line.iloc[-1]
            sig_prev = signal_line.iloc[-2]

            # ── BUY Koşulu ─────────────────────────────────────────────────
            # RSI aşırı satım bölgesinde VE MACD yukarı kesiyor
            bullish_crossover = macd_prev < sig_prev and macd_now > sig_now
            if rsi_now < self.params["rsi_oversold"] and bullish_crossover:
                reason = (
                    f"RSI={rsi_now:.1f} (aşırı satım) + MACD bullish crossover"
                )
                return self._emit_signal("BUY", symbol, close.iloc[-1], reason)

            # ── SELL Koşulu ────────────────────────────────────────────────
            # RSI aşırı alım bölgesinde VE MACD aşağı kesiyor
            bearish_crossover = macd_prev > sig_prev and macd_now < sig_now
            if rsi_now > self.params["rsi_overbought"] and bearish_crossover:
                reason = (
                    f"RSI={rsi_now:.1f} (aşırı alım) + MACD bearish crossover"
                )
                return self._emit_signal("SELL", symbol, close.iloc[-1], reason)

            # ── HOLD ───────────────────────────────────────────────────────
            return self._emit_signal(
                "HOLD",
                symbol,
                close.iloc[-1],
                f"RSI={rsi_now:.1f}, koşul sağlanmıyor",
            )

        except Exception as e:
            logger.error(f"[RSI_MACD] Sinyal hesaplama hatası: {e}")
            return self._emit_signal("HOLD", symbol, reason=f"Hata: {e}")
