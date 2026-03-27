"""
webhook/server.py
-----------------
TradingView Pine Script alert'lerini alan Flask webhook sunucusu.

TradingView'den beklenen JSON formatı:
    {
        "symbol": "THYAO",
        "action": "BUY",
        "price": 245.50,
        "timeframe": "1h",
        "strategy": "RSI_MACD"  (opsiyonel)
    }

Güvenlik: Her istekte "X-Webhook-Secret" header'ı doğrulanır.

Kullanım:
    python webhook/server.py
    # TradingView alert URL: http://your-server:5000/webhook
"""

import logging
import os
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, request

from config.settings import WEBHOOK_PORT, WEBHOOK_SECRET

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Gelen sinyalleri bellekte tut (bot döngüsü okuyacak)
pending_signals: list = []


# ── Güvenlik Dekoratörü ───────────────────────────────────────────────────

def require_secret(f):
    """
    Her webhook isteğinde secret token doğrulaması yapar.
    Header: X-Webhook-Secret: <token>
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        provided_secret = request.headers.get("X-Webhook-Secret", "")
        if WEBHOOK_SECRET and provided_secret != WEBHOOK_SECRET:
            logger.warning(
                f"Yetkisiz webhook isteği: {request.remote_addr} | "
                f"Header token geçersiz."
            )
            return jsonify({"error": "Yetkisiz erişim"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Endpoint'ler ──────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
@require_secret
def receive_webhook():
    """
    TradingView'den gelen sinyali alır, doğrular ve kuyruğa ekler.
    """
    try:
        data = request.get_json(silent=True)

        if not data:
            logger.error("Webhook: Geçersiz JSON formatı")
            return jsonify({"error": "Geçersiz JSON"}), 400

        # ── Zorunlu Alan Kontrolü ──────────────────────────────────────────
        required_fields = ["symbol", "action", "price"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            logger.error(f"Webhook: Eksik alanlar: {missing}")
            return jsonify({"error": f"Eksik alanlar: {missing}"}), 400

        # ── Değer Doğrulama ────────────────────────────────────────────────
        action = data["action"].upper()
        if action not in ("BUY", "SELL"):
            return jsonify({"error": f"Geçersiz action: {action}"}), 400

        try:
            price = float(data["price"])
        except (ValueError, TypeError):
            return jsonify({"error": "Geçersiz price değeri"}), 400

        # ── Sinyal Oluştur ─────────────────────────────────────────────────
        signal = {
            "symbol": str(data["symbol"]).upper(),
            "action": action,
            "price": price,
            "timeframe": data.get("timeframe", "1h"),
            "strategy": data.get("strategy", "TradingView"),
            "source": "tradingview_webhook",
            "received_at": datetime.now().isoformat(),
        }

        pending_signals.append(signal)

        logger.info(
            f"Webhook sinyali alındı: {signal['symbol']} {signal['action']} "
            f"@ {signal['price']} [{signal['timeframe']}]"
        )

        return jsonify({
            "status": "ok",
            "message": "Sinyal kuyruğa eklendi",
            "signal": signal,
        }), 200

    except Exception as e:
        logger.error(f"Webhook işleme hatası: {e}")
        return jsonify({"error": "Sunucu hatası"}), 500


@app.route("/signals", methods=["GET"])
def get_pending_signals():
    """
    Bekleyen sinyalleri listeler (bot döngüsü için endpoint).
    Sinyaller okunduktan sonra listeden çıkarılır.
    """
    signals = pending_signals.copy()
    pending_signals.clear()

    return jsonify({
        "count": len(signals),
        "signals": signals,
    }), 200


@app.route("/health", methods=["GET"])
def health_check():
    """Webhook sunucusunun çalışıp çalışmadığını kontrol eder."""
    return jsonify({
        "status": "healthy",
        "pending_signals": len(pending_signals),
        "timestamp": datetime.now().isoformat(),
    }), 200


@app.route("/test", methods=["POST"])
def test_webhook():
    """
    Webhook'u test etmek için örnek sinyal gönderir (güvenlik kontrolü yok).
    Sadece geliştirme ortamında kullan!
    """
    if os.getenv("FLASK_ENV") != "development":
        return jsonify({"error": "Test endpoint sadece development modunda aktif"}), 403

    test_signal = {
        "symbol": "THYAO",
        "action": "BUY",
        "price": 245.50,
        "timeframe": "1h",
        "strategy": "TEST",
    }
    pending_signals.append({
        **test_signal,
        "source": "test",
        "received_at": datetime.now().isoformat(),
    })

    return jsonify({"status": "ok", "test_signal": test_signal}), 200


# ── Uygulama Başlatma ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info(f"Webhook sunucusu başlatılıyor: port={WEBHOOK_PORT}")

    if not WEBHOOK_SECRET:
        logger.warning("UYARI: WEBHOOK_SECRET ayarlanmamış! Webhook güvensiz çalışıyor.")

    app.run(
        host="0.0.0.0",
        port=WEBHOOK_PORT,
        debug=False,  # Production'da False bırak
    )
