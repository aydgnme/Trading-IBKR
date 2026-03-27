"""
config/settings.py
------------------
Merkezi ayar dosyası. Tüm API parametreleri, semboller ve genel
bot davranışları burada tanımlanır. .env dosyasından yüklenir,
asla sabit kodlanmış değer kullanılmaz.
"""

import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# ── IBKR Bağlantı Ayarları ─────────────────────────────────────────────────
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", 7497))   # Paper: 7497 | Gerçek: 7496
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", 1))

# ── Trading Modu ───────────────────────────────────────────────────────────
IS_PAPER_TRADING = os.getenv("IS_PAPER_TRADING", "True").lower() == "true"

# ── Telegram Bildirimleri ──────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Webhook Güvenlik ───────────────────────────────────────────────────────
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 5000))

# ── Semboller ──────────────────────────────────────────────────────────────

# BVB (Bükreş Borsası) — devre dışı, ileride aktif edilecek
# BVB_SYMBOLS = ["TLV.RO", "SNP.RO", "TGN.RO", "BRD.RO", "SNG.RO"]
BVB_SYMBOLS = []

# BIST (Borsa İstanbul) — devre dışı, ileride aktif edilecek
# BIST_SYMBOLS = ["THYAO.IS", "GARAN.IS", "ASELS.IS", "EREGL.IS", "BIMAS.IS"]
BIST_SYMBOLS = []

# ABD Borsası (SMART routing) — aktif
US_SYMBOLS = ["AAPL", "MSFT", "TSLA", "NVDA", "SPY", "AMZN", "GOOGL", "META"]

# Forex çiftleri — devre dışı, izin çözülene kadar beklemede
FOREX_PAIRS = []

# ── Avrupa ETF Sembolleri ──────────────────────────────────────────────────
# Her sembol → IBKR exchange kodu eşleştirmesi
EU_EXCHANGE_MAP = {
    "EXW1.DE": "SMART",   # iShares MSCI World — Frankfurt (Xetra), EUR
    "EXS1.DE": "SMART",   # iShares Core DAX — Frankfurt (Xetra), EUR
    "VEUR.AS": "SMART",   # Vanguard FTSE Europe ETF — Amsterdam, EUR
    "IWDA.AS": "SMART",   # iShares Core MSCI World — Amsterdam, EUR
    "EUNL.DE": "SMART",   # iShares Core MSCI World — Frankfurt (Xetra), EUR
    "SXR8.DE": "SMART",   # iShares Core S&P500 — Frankfurt (Xetra), EUR
    "EXSA.DE": "SMART",   # iShares STOXX Europe 600 — Frankfurt (Xetra), EUR
}
EU_SYMBOLS = list(EU_EXCHANGE_MAP.keys())

# ── Piyasa Çalışma Saatleri (UTC) ──────────────────────────────────────────
MARKET_HOURS = {
    "BVB": {
        "timezone": "Europe/Bucharest",
        "open": "10:00",
        "close": "18:30",
        "weekdays": [0, 1, 2, 3, 4],  # Pazartesi-Cuma
    },
    "BIST": {
        "timezone": "Europe/Istanbul",
        "open": "10:00",
        "close": "18:00",
        "weekdays": [0, 1, 2, 3, 4],
    },
    "FOREX": {
        "timezone": "UTC",
        "open": "00:00",
        "close": "23:59",
        "weekdays": [0, 1, 2, 3, 4],  # 24/5
    },
    "EU": {
        "timezone": "Europe/Berlin",   # CET/CEST — Frankfurt, Paris, Amsterdam
        "open": "10:00",
        "close": "18:30",
        "weekdays": [0, 1, 2, 3, 4],  # Pazartesi-Cuma
    },
    "US": {
        "timezone": "America/New_York",
        "open": "09:30",
        "close": "16:00",
        "weekdays": [0, 1, 2, 3, 4],  # Pazartesi-Cuma EST
    },
}

# ── Timeframe Ayarları ─────────────────────────────────────────────────────
TIMEFRAMES = {
    "1m": "1 min",
    "5m": "5 mins",
    "15m": "15 mins",
    "1h": "1 hour",
    "1d": "1 day",
}

# ── Başlangıç Sermayesi ────────────────────────────────────────────────────
INITIAL_CAPITAL_USD = 10_000

# ── Loglama ────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "trading_bot.log"

# ── Veritabanı ─────────────────────────────────────────────────────────────
DB_PATH = "data/trading.db"
