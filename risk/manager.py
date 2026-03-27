"""
risk/manager.py
---------------
Risk yönetimi modülü. Her işlem açılmadan önce bu sınıf:
  - Pozisyon boyutunu hesaplar (sermayenin max %2 riski)
  - ATR bazlı stop-loss fiyatı belirler
  - Take-profit fiyatını hesaplar (minimum 1:2 risk/ödül)
  - Maksimum açık pozisyon sayısını kontrol eder
  - Günlük kayıp limitini izler
  - Sektör korelasyonunu kontrol eder

Kullanım:
    manager = RiskManager(capital=10000)
    result = manager.evaluate(signal="BUY", symbol="TLV", entry_price=45.0, df=df)
    if result["approved"]:
        # İşlemi aç
        quantity = result["quantity"]
        stop_loss = result["stop_loss"]
        take_profit = result["take_profit"]
"""

import logging
from datetime import date
from typing import Optional

import pandas as pd
import pandas_ta as ta

from config.risk_params import (
    ATR_MULTIPLIER,
    ATR_PERIOD,
    COMMISSION_RATE,
    DAILY_LOSS_LIMIT,
    FOREX_MAX_UNITS,
    MAX_OPEN_POSITIONS,
    MAX_RISK_PER_TRADE,
    MAX_SAME_SECTOR_POSITIONS,
    MIN_RISK_REWARD,
    SECTOR_MAP,
)

logger = logging.getLogger(__name__)


class RiskManager:
    """İşlem risk değerlendirmesi ve pozisyon boyutu hesaplayan sınıf."""

    def __init__(self, capital: float):
        """
        Args:
            capital: Mevcut toplam sermaye (USD/RON/TRY)
        """
        self.capital = capital
        self.open_positions: list = []     # Açık pozisyonlar listesi
        self.daily_pnl: float = 0.0        # Bugünkü kâr/zarar
        self.daily_date: date = date.today()

    # ── Ana Değerlendirme Metodu ───────────────────────────────────────────

    def evaluate(
        self,
        signal: str,
        symbol: str,
        entry_price: float,
        df: pd.DataFrame,
        currency: str = "USD",
        market: str = None,
    ) -> dict:
        """
        İşlem için kapsamlı risk değerlendirmesi yapar.

        Args:
            signal: "BUY" veya "SELL"
            symbol: Hisse sembolü
            entry_price: Giriş fiyatı
            df: OHLCV DataFrame (ATR hesabı için)
            currency: Para birimi

        Returns:
            dict: {
                "approved": bool,
                "reason": str,
                "quantity": int,
                "stop_loss": float,
                "take_profit": float,
                "risk_amount": float,
                "atr": float,
            }
        """
        # Günlük tarihi sıfırla
        self._reset_daily_if_needed()

        rejected = lambda reason: {
            "approved": False,
            "reason": reason,
            "quantity": 0,
            "stop_loss": 0,
            "take_profit": 0,
            "risk_amount": 0,
            "atr": 0,
        }

        # ── Kontroller ─────────────────────────────────────────────────────

        # 1. Günlük kayıp limiti
        daily_loss_limit = self.capital * DAILY_LOSS_LIMIT
        if self.daily_pnl <= -daily_loss_limit:
            reason = (
                f"Günlük kayıp limiti aşıldı: "
                f"{self.daily_pnl:.2f} <= -{daily_loss_limit:.2f}"
            )
            logger.warning(f"[RiskManager] {reason}")
            return rejected(reason)

        # 2. Aynı sembolde zaten açık pozisyon var mı?
        already_open = any(p.get("symbol") == symbol for p in self.open_positions)
        if already_open:
            reason = f"Zaten açık pozisyon var: {symbol}"
            logger.info(f"[RiskManager] {reason}")
            return rejected(reason)

        # 3. Maksimum açık pozisyon (farklı sembollerde eş zamanlı 5'e kadar)
        if len(self.open_positions) >= MAX_OPEN_POSITIONS:
            reason = f"Maksimum açık pozisyon sayısına ulaşıldı: {MAX_OPEN_POSITIONS}"
            logger.warning(f"[RiskManager] {reason}")
            return rejected(reason)

        # 4. Sektör korelasyon kontrolü
        sector_check = self._check_sector_correlation(symbol)
        if not sector_check["ok"]:
            logger.warning(f"[RiskManager] {sector_check['reason']}")
            return rejected(sector_check["reason"])

        # 5. ATR bazlı stop-loss hesapla
        atr = self._calculate_atr(df)
        if atr is None or atr <= 0:
            reason = "ATR hesaplanamadı, stop-loss belirlenemiyor."
            logger.error(f"[RiskManager] {reason}")
            return rejected(reason)

        # 6. Stop-loss ve take-profit fiyatları
        stop_distance = atr * ATR_MULTIPLIER

        if signal == "BUY":
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + (stop_distance * MIN_RISK_REWARD)
        elif signal == "SELL":
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - (stop_distance * MIN_RISK_REWARD)
        else:
            return rejected(f"Geçersiz sinyal: {signal}")

        # 6. Pozisyon boyutu hesapla
        risk_per_trade = self.capital * MAX_RISK_PER_TRADE  # Örn: 10000 * 0.02 = 200
        risk_per_share = abs(entry_price - stop_loss)

        if risk_per_share <= 0:
            return rejected("Stop-loss mesafesi sıfır, hesaplama yapılamıyor.")

        quantity = int(risk_per_trade / risk_per_share)

        if quantity <= 0:
            return rejected(
                f"Hesaplanan adet 0: risk={risk_per_trade:.2f}, "
                f"risk/hisse={risk_per_share:.4f}"
            )

        # Forex pozisyon boyutu üst sınırı (izin limitini aşmamak için)
        if market == "FOREX" and quantity > FOREX_MAX_UNITS:
            logger.info(
                f"[RiskManager] Forex lot sınırı uygulandı: "
                f"{quantity} → {FOREX_MAX_UNITS} birim ({symbol})"
            )
            quantity = FOREX_MAX_UNITS

        actual_risk = quantity * risk_per_share
        commission_cost = quantity * entry_price * COMMISSION_RATE

        logger.info(
            f"[RiskManager] ONAYLANDI | {symbol} {signal} | "
            f"Adet={quantity} | Giriş={entry_price:.4f} | "
            f"SL={stop_loss:.4f} | TP={take_profit:.4f} | "
            f"Risk={actual_risk:.2f} {currency} | ATR={atr:.4f}"
        )

        return {
            "approved": True,
            "reason": "Tüm risk kontrolleri geçildi.",
            "quantity": quantity,
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "risk_amount": round(actual_risk, 2),
            "commission": round(commission_cost, 2),
            "atr": round(atr, 4),
            "currency": currency,
        }

    # ── Pozisyon Takibi ───────────────────────────────────────────────────

    def add_position(self, position: dict):
        """
        Yeni açılan pozisyonu listeye ekler.

        Args:
            position: {"symbol": str, "direction": str, "entry": float, ...}
        """
        self.open_positions.append(position)
        logger.info(
            f"[RiskManager] Pozisyon eklendi: {position.get('symbol')} "
            f"| Toplam açık: {len(self.open_positions)}"
        )

    def remove_position(self, symbol: str):
        """
        Kapatılan pozisyonu listeden çıkarır.

        Args:
            symbol: Kapatılan hissenin sembolü
        """
        self.open_positions = [
            p for p in self.open_positions if p.get("symbol") != symbol
        ]
        logger.info(
            f"[RiskManager] Pozisyon silindi: {symbol} "
            f"| Toplam açık: {len(self.open_positions)}"
        )

    def update_daily_pnl(self, pnl_change: float):
        """
        Günlük P&L'yi günceller.

        Args:
            pnl_change: Gerçekleşen kâr/zarar değişimi
        """
        self._reset_daily_if_needed()
        self.daily_pnl += pnl_change
        logger.debug(f"[RiskManager] Günlük P&L: {self.daily_pnl:.2f}")

    def update_capital(self, new_capital: float):
        """Sermayeyi günceller."""
        self.capital = new_capital
        logger.debug(f"[RiskManager] Sermaye güncellendi: {new_capital:.2f}")

    # ── Yardımcı Metodlar ─────────────────────────────────────────────────

    def _calculate_atr(self, df: pd.DataFrame) -> Optional[float]:
        """
        ATR (Average True Range) hesaplar.

        Args:
            df: OHLCV DataFrame

        Returns:
            float: Son ATR değeri
        """
        try:
            if df is None or len(df) < ATR_PERIOD + 1:
                return None

            atr_series = ta.atr(
                df["high"].astype(float),
                df["low"].astype(float),
                df["close"].astype(float),
                length=ATR_PERIOD,
            )

            if atr_series is None or atr_series.isna().all():
                return None

            return float(atr_series.iloc[-1])

        except Exception as e:
            logger.error(f"ATR hesaplama hatası: {e}")
            return None

    def _check_sector_correlation(self, symbol: str) -> dict:
        """
        Aynı sektörde çok fazla pozisyon olup olmadığını kontrol eder.

        Args:
            symbol: Kontrol edilecek sembol

        Returns:
            dict: {"ok": bool, "reason": str}
        """
        sector = SECTOR_MAP.get(symbol)

        if sector is None:
            # Sektör bilinmiyorsa geçir
            return {"ok": True, "reason": "Sektör bilgisi yok, kontrol atlandı."}

        # Aynı sektördeki açık pozisyonları say
        same_sector_count = sum(
            1
            for pos in self.open_positions
            if SECTOR_MAP.get(pos.get("symbol")) == sector
        )

        if same_sector_count >= MAX_SAME_SECTOR_POSITIONS:
            return {
                "ok": False,
                "reason": (
                    f"Sektör limiti aşıldı ({sector}): "
                    f"{same_sector_count} >= {MAX_SAME_SECTOR_POSITIONS}"
                ),
            }

        return {"ok": True, "reason": "Sektör kontrolü geçildi."}

    def _reset_daily_if_needed(self):
        """Yeni güne geçilmişse günlük P&L'yi sıfırlar."""
        today = date.today()
        if self.daily_date != today:
            logger.info(
                f"[RiskManager] Yeni gün: günlük P&L sıfırlandı "
                f"({self.daily_date} → {today})"
            )
            self.daily_pnl = 0.0
            self.daily_date = today

    def get_status(self) -> dict:
        """
        Mevcut risk durumunu özetler.

        Returns:
            dict: Risk durumu özeti
        """
        return {
            "capital": self.capital,
            "open_positions": len(self.open_positions),
            "max_positions": MAX_OPEN_POSITIONS,
            "daily_pnl": self.daily_pnl,
            "daily_loss_limit": self.capital * DAILY_LOSS_LIMIT,
            "daily_limit_used_pct": (
                abs(self.daily_pnl) / (self.capital * DAILY_LOSS_LIMIT) * 100
                if self.daily_pnl < 0
                else 0
            ),
            "positions": [p.get("symbol") for p in self.open_positions],
        }
