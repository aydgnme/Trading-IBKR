"""
notifications/telegram.py
--------------------------
Telegram Bot API üzerinden bildirim gönderen modül.

Bildirim tipleri:
  - İşlem açıldı (sembol, yön, giriş, stop-loss, hedef)
  - İşlem kapandı (kâr/zarar detayları)
  - Günlük özet (toplam P&L, açık pozisyonlar)
  - Hata bildirimi (bağlantı koptu, emir reddedildi)

Kullanım:
    notifier = TelegramNotifier()
    notifier.send_trade_opened("TLV", "BUY", 45.0, 43.0, 49.0)
    notifier.send_daily_summary(pnl=250.0, open_positions=3)
"""

import logging
from datetime import datetime

import requests

from config.settings import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Telegram Bot üzerinden mesaj gönderen sınıf."""

    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "Telegram bildirimleri devre dışı: "
                "TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID eksik."
            )

    # ── Bildirim Metodları ────────────────────────────────────────────────

    def send_trade_opened(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: int = 0,
        strategy: str = "",
        currency: str = "USD",
    ):
        """
        İşlem açıldığında bildirim gönderir.

        Args:
            symbol: Hisse sembolü
            direction: "BUY" veya "SELL"
            entry_price: Giriş fiyatı
            stop_loss: Stop-loss fiyatı
            take_profit: Take-profit fiyatı
            quantity: Hisse adedi
            strategy: Kullanılan strateji adı
            currency: Para birimi
        """
        emoji = "🟢" if direction == "BUY" else "🔴"
        risk = abs(entry_price - stop_loss) * quantity if quantity else 0
        reward = abs(take_profit - entry_price) * quantity if quantity else 0

        message = (
            f"{emoji} *İŞLEM AÇILDI*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Sembol: `{symbol}`\n"
            f"📈 Yön: `{direction}`\n"
            f"💰 Giriş: `{entry_price:.4f} {currency}`\n"
            f"🛑 Stop-Loss: `{stop_loss:.4f} {currency}`\n"
            f"🎯 Hedef: `{take_profit:.4f} {currency}`\n"
            f"📦 Adet: `{quantity}`\n"
            f"⚠️ Risk: `{risk:.2f} {currency}`\n"
            f"💎 Ödül: `{reward:.2f} {currency}`\n"
            f"🤖 Strateji: `{strategy}`\n"
            f"🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        self._send(message)

    def send_trade_closed(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        pnl: float,
        currency: str = "USD",
        reason: str = "",
    ):
        """
        İşlem kapandığında kâr/zarar bildirimi gönderir.

        Args:
            symbol: Hisse sembolü
            direction: "BUY" veya "SELL"
            entry_price: Giriş fiyatı
            exit_price: Çıkış fiyatı
            quantity: Hisse adedi
            pnl: Gerçekleşen kâr/zarar
            currency: Para birimi
            reason: Kapanış nedeni (stop-loss, take-profit, manual)
        """
        emoji = "✅" if pnl >= 0 else "❌"
        pnl_sign = "+" if pnl >= 0 else ""
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        if direction == "SELL":
            pnl_pct = -pnl_pct

        message = (
            f"{emoji} *İŞLEM KAPANDI*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Sembol: `{symbol}`\n"
            f"📈 Yön: `{direction}`\n"
            f"💰 Giriş: `{entry_price:.4f}` → Çıkış: `{exit_price:.4f}`\n"
            f"📦 Adet: `{quantity}`\n"
            f"{'🟢' if pnl >= 0 else '🔴'} P&L: "
            f"`{pnl_sign}{pnl:.2f} {currency}` ({pnl_sign}{pnl_pct:.2f}%)\n"
            f"📝 Neden: `{reason}`\n"
            f"🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        self._send(message)

    def send_daily_summary(
        self,
        total_pnl: float,
        open_positions: int,
        win_count: int = 0,
        loss_count: int = 0,
        currency_breakdown: dict = None,
    ):
        """
        Günlük özet bildirimi gönderir.

        Args:
            total_pnl: Bugünkü toplam kâr/zarar
            open_positions: Açık pozisyon sayısı
            win_count: Kazanan işlem sayısı
            loss_count: Kaybeden işlem sayısı
            currency_breakdown: Para birimi bazında P&L ({"RON": 120, "TRY": -50})
        """
        total_trades = win_count + loss_count
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        pnl_sign = "+" if total_pnl >= 0 else ""

        currency_lines = ""
        if currency_breakdown:
            for curr, amount in currency_breakdown.items():
                sign = "+" if amount >= 0 else ""
                currency_lines += f"  • {curr}: `{sign}{amount:.2f}`\n"

        message = (
            f"📊 *GÜNLÜK ÖZET*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{pnl_emoji} Toplam P&L: `{pnl_sign}{total_pnl:.2f}`\n"
            f"{currency_lines}"
            f"🏆 Kazanan: `{win_count}` | ❌ Kaybeden: `{loss_count}`\n"
            f"📊 Kazanma Oranı: `{win_rate:.1f}%`\n"
            f"📂 Açık Pozisyon: `{open_positions}`\n"
            f"🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        self._send(message)

    def send_error(self, error_type: str, details: str):
        """
        Hata bildirimi gönderir (bağlantı koptu, emir reddedildi, vb.).

        Args:
            error_type: Hata tipi (örn: "IBKR Bağlantı Hatası")
            details: Hata detayları
        """
        message = (
            f"🚨 *HATA: {error_type}*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"```{details[:500]}```\n"
            f"🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        self._send(message)

    def send_bot_status(self, status: str, details: str = ""):
        """
        Bot durumu bildirimi (başlatıldı/durduruldu).

        Args:
            status: "STARTED", "STOPPED", "PAUSED"
            details: Ek bilgi
        """
        emoji = {"STARTED": "🟢", "STOPPED": "🔴", "PAUSED": "🟡"}.get(status, "⚪")

        message = (
            f"{emoji} *BOT {status}*\n"
            f"━━━━━━━━━━━━━━━\n"
        )
        if details:
            message += f"ℹ️ {details}\n"
        message += f"🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"

        self._send(message)

    def send_message(self, text: str) -> bool:
        """Serbest format mesaj gönderir."""
        return self._send(text)

    # ── Gönderme Altyapısı ────────────────────────────────────────────────

    def _send(self, message: str) -> bool:
        """
        Telegram API'sine mesaj gönderir.

        Args:
            message: Markdown formatında mesaj

        Returns:
            bool: Başarılıysa True
        """
        if not self.enabled:
            logger.debug(f"[Telegram] Bildirim devre dışı: {message[:80]}...")
            return False

        try:
            url = TELEGRAM_API.format(token=self.token)
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            logger.debug("Telegram bildirimi gönderildi.")
            return True

        except requests.exceptions.Timeout:
            logger.error("Telegram API zaman aşımı.")
            return False
        except requests.exceptions.HTTPError as e:
            logger.error(f"Telegram HTTP hatası: {e}")
            return False
        except Exception as e:
            logger.error(f"Telegram gönderme hatası: {e}")
            return False
