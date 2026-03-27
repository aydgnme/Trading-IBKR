"""
strategies/base.py
------------------
Tüm stratejilerin miras aldığı temel sınıf.
Her strateji bu sınıfı extend eder ve generate_signal() metodunu
override etmek zorundadır.

Kullanım:
    class MyStrategy(BaseStrategy):
        def generate_signal(self, df):
            # ... sinyal mantığı ...
            return "BUY"
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Geçerli sinyal değerleri
VALID_SIGNALS = {"BUY", "SELL", "HOLD"}


class BaseStrategy(ABC):
    """Tüm trading stratejilerinin temel sınıfı."""

    def __init__(self, name: str, params: dict = None):
        """
        Args:
            name: Strateji adı (loglama ve raporlama için)
            params: Strateji parametreleri (örn: {"rsi_period": 14})
        """
        self.name = name
        self.params = params or {}
        self.signal_history = []  # Geçmiş sinyal kaydı
        self._validate_params()

    # ── Soyut Metod ───────────────────────────────────────────────────────

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> str:
        """
        Verilen OHLCV verisinden sinyal üretir.

        Args:
            df: OHLCV DataFrame (open, high, low, close, volume sütunları)

        Returns:
            str: "BUY", "SELL" veya "HOLD"
        """
        pass

    # ── Parametre Doğrulama ───────────────────────────────────────────────

    def _validate_params(self):
        """
        Strateji parametrelerini doğrular.
        Alt sınıflar bu metodu override edebilir.
        """
        pass

    def _require_param(self, key: str, min_val: float = None, max_val: float = None):
        """
        Belirli bir parametrenin varlığını ve değer aralığını kontrol eder.

        Args:
            key: Parametre adı
            min_val: Minimum geçerli değer (opsiyonel)
            max_val: Maksimum geçerli değer (opsiyonel)
        """
        if key not in self.params:
            raise ValueError(f"[{self.name}] Eksik parametre: '{key}'")

        val = self.params[key]

        if min_val is not None and val < min_val:
            raise ValueError(
                f"[{self.name}] '{key}' = {val} geçersiz, minimum {min_val} olmalı."
            )

        if max_val is not None and val > max_val:
            raise ValueError(
                f"[{self.name}] '{key}' = {val} geçersiz, maksimum {max_val} olmalı."
            )

    # ── Sinyal Yardımcıları ───────────────────────────────────────────────

    def _emit_signal(
        self, signal: str, symbol: str = "", price: float = 0.0, reason: str = ""
    ) -> str:
        """
        Sinyal üretir, doğrular ve geçmişe kaydeder.

        Args:
            signal: "BUY", "SELL" veya "HOLD"
            symbol: Hisse sembolü
            price: Anlık fiyat
            reason: Sinyal gerekçesi

        Returns:
            str: Doğrulanmış sinyal
        """
        if signal not in VALID_SIGNALS:
            logger.warning(
                f"[{self.name}] Geçersiz sinyal '{signal}', HOLD olarak işleniyor."
            )
            signal = "HOLD"

        entry = {
            "strategy": self.name,
            "signal": signal,
            "symbol": symbol,
            "price": price,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        self.signal_history.append(entry)

        if signal != "HOLD":
            logger.info(
                f"[{self.name}] SİNYAL: {signal} | {symbol} @ {price:.4f} | {reason}"
            )

        return signal

    def get_last_signal(self) -> Optional[dict]:
        """En son üretilen sinyali döndürür."""
        return self.signal_history[-1] if self.signal_history else None

    def get_signal_count(self) -> dict:
        """Sinyal tipine göre sayım döndürür."""
        counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for entry in self.signal_history:
            counts[entry["signal"]] += 1
        return counts

    # ── Veri Doğrulama ────────────────────────────────────────────────────

    def _check_data(self, df: pd.DataFrame, min_rows: int = 50) -> bool:
        """
        DataFrame'in yeterli veri içerip içermediğini kontrol eder.

        Args:
            df: Kontrol edilecek DataFrame
            min_rows: Minimum satır sayısı

        Returns:
            bool: Veri yeterliyse True
        """
        if df is None or df.empty:
            logger.warning(f"[{self.name}] Boş DataFrame, sinyal üretilemiyor.")
            return False

        if len(df) < min_rows:
            logger.warning(
                f"[{self.name}] Yetersiz veri: {len(df)} satır var, "
                f"minimum {min_rows} gerekli."
            )
            return False

        required_cols = {"close", "high", "low", "open", "volume"}
        missing = required_cols - set(df.columns.str.lower())
        if missing:
            logger.error(f"[{self.name}] Eksik sütunlar: {missing}")
            return False

        return True

    def __repr__(self) -> str:
        return f"<Strategy: {self.name} | params={self.params}>"
