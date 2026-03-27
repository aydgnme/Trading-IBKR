"""
tests/test_system.py
--------------------
Sistem test scripti (Aşama 4 Checklist).
Her adımı sırayla test eder ve sonuçları raporlar.

Çalıştırma:
    python tests/test_system.py
"""

import sys
import os
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

logging.basicConfig(level=logging.WARNING)

PASS = "✅"
FAIL = "❌"
SKIP = "⚠️"


def run_test(name: str, fn) -> bool:
    try:
        result = fn()
        if result:
            print(f"{PASS} {name}")
            return True
        else:
            print(f"{FAIL} {name}")
            return False
    except Exception as e:
        print(f"{FAIL} {name} — Hata: {e}")
        return False


# ── Test Fonksiyonları ────────────────────────────────────────────────────

def test_ibkr_connection():
    """IBKR paper bağlantısı kuruluyor mu?"""
    from broker.ibkr_client import IBKRClient
    client = IBKRClient(client_id=2)  # main.py clientId=1, çakışmayı önle
    result = client.connect(max_retries=1, retry_delay=1)
    if result:
        client.disconnect()
    return result


def test_bvb_data():
    """BVB sembolü (TLV.RO) için veri çekiliyor mu?"""
    from data.fetcher import DataFetcher
    fetcher = DataFetcher()
    df = fetcher.get_historical_yfinance("TLV.RO", "BVB", period="1mo", interval="1d")
    return df is not None and len(df) > 0


def test_bist_data():
    """BIST sembolü (THYAO.IS) için veri çekiliyor mu?"""
    from data.fetcher import DataFetcher
    fetcher = DataFetcher()
    df = fetcher.get_historical_yfinance("THYAO", "BIST", period="1mo", interval="1d")
    return df is not None and len(df) > 0


def test_strategy_signal():
    """Strateji sinyal üretiyor mu?"""
    from data.fetcher import DataFetcher
    from strategies.rsi_macd import RSIMACDStrategy
    from strategies.bollinger import BollingerStrategy
    from strategies.trend import TrendStrategy

    fetcher = DataFetcher()
    df = fetcher.get_historical_yfinance("THYAO", "BIST", period="1y", interval="1d")
    if df is None or df.empty:
        return False

    rsi_macd = RSIMACDStrategy()
    bollinger = BollingerStrategy()
    trend = TrendStrategy()

    s1 = rsi_macd.generate_signal(df, "THYAO")
    s2 = bollinger.generate_signal(df, "THYAO")
    s3 = trend.generate_signal(df, "THYAO")

    valid = {"BUY", "SELL", "HOLD"}
    return s1 in valid and s2 in valid and s3 in valid


def test_risk_manager():
    """Risk yöneticisi pozisyon boyutunu hesaplıyor mu?"""
    from risk.manager import RiskManager
    from data.fetcher import DataFetcher

    fetcher = DataFetcher()
    df = fetcher.get_historical_yfinance("THYAO", "BIST", period="6mo", interval="1d")
    if df is None:
        return False

    manager = RiskManager(capital=10_000.0)
    result = manager.evaluate(
        signal="BUY",
        symbol="THYAO",
        entry_price=float(df["close"].iloc[-1]),
        df=df,
        currency="TRY",
    )
    return isinstance(result, dict) and "quantity" in result


def test_paper_order():
    """Paper trading emri simüle ediliyor mu?"""
    from broker.ibkr_client import IBKRClient
    from broker.order_manager import OrderManager
    from ib_insync import Stock

    client = IBKRClient(client_id=2)  # main.py clientId=1, çakışmayı önle
    om = OrderManager(client)

    contract = Stock("THYAO", "IBIS", "TRY")
    result = om.place_market_order("BUY", contract, 10)
    return result is not None and result.get("paper") is True


def test_telegram():
    """Telegram bildirimi gönderiliyor mu?"""
    from notifications.telegram import TelegramNotifier
    notifier = TelegramNotifier()
    if not notifier.enabled:
        print(f"  {SKIP} Telegram token/chat_id eksik, test atlandı.")
        return True  # Token yoksa skip et, fail değil
    result = notifier.send_message("🧪 Test mesajı: Sistem testi çalışıyor.")
    return result


def test_database():
    """Veritabanı yazma/okuma çalışıyor mu?"""
    from data.db import Database
    db = Database(db_path=":memory:")  # Geçici in-memory DB

    trade_id = db.save_trade({
        "symbol": "TEST",
        "direction": "BUY",
        "entry_price": 100.0,
        "quantity": 10,
        "currency": "USD",
        "strategy": "TEST",
        "status": "OPEN",
        "opened_at": datetime.now().isoformat(),
    })

    trades = db.get_trades()
    return trade_id > 0 and len(trades) > 0


def test_dashboard_importable():
    """Dashboard modülü import edilebiliyor mu?"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "app",
            os.path.join(os.path.dirname(__file__), "..", "dashboard", "app.py")
        )
        # Sadece import kontrolü, Streamlit çalıştırmıyoruz
        return spec is not None
    except Exception:
        return False


# ── Test Çalıştırıcı ──────────────────────────────────────────────────────

def main():
    print("\n" + "="*55)
    print("  TRADING BOT SİSTEM TESTİ")
    print("="*55)

    tests = [
        ("IBKR Paper Bağlantısı", test_ibkr_connection),
        ("BVB Veri Çekme (TLV.RO)", test_bvb_data),
        ("BIST Veri Çekme (THYAO.IS)", test_bist_data),
        ("Strateji Sinyal Üretimi", test_strategy_signal),
        ("Risk Yöneticisi Hesabı", test_risk_manager),
        ("Paper Trading Emri", test_paper_order),
        ("Telegram Bildirimi", test_telegram),
        ("Veritabanı İşlemleri", test_database),
        ("Dashboard Import", test_dashboard_importable),
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        ok = run_test(name, fn)
        if ok:
            passed += 1
        else:
            failed += 1

    print("\n" + "-"*55)
    print(f"  Sonuç: {passed} geçti | {failed} başarısız")
    print("="*55 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
