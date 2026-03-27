"""
main.py
-------
Trading botunun ana giriş noktası ve kontrol döngüsü.

Döngü mantığı:
  1. Piyasa saatlerini kontrol et (BVB/BIST/Forex ayrı saatler)
  2. Her aktif sembol için strateji sinyali üret
  3. Sinyal varsa risk yöneticisinden geçir
  4. Onaylanırsa IBKR'ye emir gönder
  5. Açık pozisyonları izle, stop-loss tetiklenirse kapat
  6. IS_PAPER_TRADING=True ise önce logla, ardından IBKR paper account'a gönder (TWS simüle eder)

Çalıştırma:
    python main.py
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime

import pytz

from broker.ibkr_client import IBKRClient
from broker.order_manager import OrderManager
from config.settings import (
    EU_EXCHANGE_MAP,
    EU_SYMBOLS,
    FOREX_PAIRS,
    IS_PAPER_TRADING,
    LOG_FILE,
    LOG_LEVEL,
    MARKET_HOURS,
    US_SYMBOLS,
)
from config.risk_params import MAX_OPEN_POSITIONS
from data.db import Database
from data.fetcher import DataFetcher
from notifications.telegram import TelegramNotifier
from risk.manager import RiskManager
from strategies.bollinger import BollingerStrategy
from strategies.rsi_macd import RSIMACDStrategy
from strategies.trend import TrendStrategy

# ── Loglama Yapılandırması ─────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Bot çalışma bayrağı (SIGTERM/SIGINT ile durdurulabilir)
_running = True


def _handle_shutdown(signum, frame):
    """Graceful shutdown için sinyal handler."""
    global _running
    logger.info("Kapatma sinyali alındı. Bot durduruluyor...")
    _running = False


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


# ── Piyasa Saati Kontrolü ──────────────────────────────────────────────────

def is_market_open(market: str) -> bool:
    """
    Belirtilen piyasanın şu an açık olup olmadığını kontrol eder.

    Args:
        market: "BVB", "BIST" veya "FOREX"

    Returns:
        bool: Piyasa açıksa True
    """
    config = MARKET_HOURS.get(market)
    if not config:
        return False

    tz = pytz.timezone(config["timezone"])
    now = datetime.now(tz)

    # Hafta sonu kontrolü
    if now.weekday() not in config["weekdays"]:
        return False

    # Saat kontrolü
    open_h, open_m = map(int, config["open"].split(":"))
    close_h, close_m = map(int, config["close"].split(":"))

    open_time = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_time = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    return open_time <= now <= close_time


# ── Strateji Sinyal Motoru ─────────────────────────────────────────────────

def _resolve_signals(signals: dict) -> tuple[str, str, bool]:
    """
    Birden fazla strateji sinyalini uzlaştırır.

    Args:
        signals: {strateji_adı: sinyal} — örn: {"RSI_MACD": "BUY", "Bollinger_RSI": "BUY"}

    Returns:
        (karar, strateji_listesi, güçlü_sinyal_mi)
        karar: "BUY", "SELL" veya "HOLD"
        strateji_listesi: karar veren stratejilerin adları (virgülle)
        güçlü_sinyal_mi: 2+ strateji aynı yönde ise True
    """
    buy_strategies  = [s for s, sig in signals.items() if sig == "BUY"]
    sell_strategies = [s for s, sig in signals.items() if sig == "SELL"]

    # Çelişki: hem BUY hem SELL sinyali var
    if buy_strategies and sell_strategies:
        return "HOLD", "", False

    if len(buy_strategies) >= 2:
        return "BUY", ", ".join(buy_strategies), True
    if len(sell_strategies) >= 2:
        return "SELL", ", ".join(sell_strategies), True
    if len(buy_strategies) == 1:
        return "BUY", buy_strategies[0], False
    if len(sell_strategies) == 1:
        return "SELL", sell_strategies[0], False

    return "HOLD", "", False


def run_strategies_for_symbol(
    symbol: str,
    market: str,
    fetcher: DataFetcher,
    strategies: list,
    risk_manager: RiskManager,
    order_manager: OrderManager,
    ibkr_client: IBKRClient,
    db: Database,
    notifier: TelegramNotifier,
    exchange: str = None,
) -> dict:
    """
    Bir sembol için 3 stratejiyi çalıştırır, sinyalleri uzlaştırır ve işlem açar.

    Returns:
        dict: {"signal": "BUY"/"SELL"/"HOLD", "traded": bool}
    """
    _no_trade = lambda sig="HOLD": {"signal": sig, "traded": False}

    # Veri çek
    df = fetcher.get_historical_yfinance(symbol, market, period="3mo", interval="1h")
    if df is None:
        logger.warning(f"Veri çekilemedi: {symbol}")
        return _no_trade()

    if market == "BVB":
        currency = "RON"
    elif market in ("US", "FOREX"):
        currency = "USD"
    elif market == "EU":
        currency = "EUR"
    else:
        currency = "TRY"

    # ── 1. Her stratejiyi bağımsız çalıştır, sinyalleri topla ─────────────
    signals = {}
    for strategy in strategies:
        try:
            sig = strategy.generate_signal(df, symbol)
            signals[strategy.name] = sig

            last = strategy.get_last_signal()
            if last:
                db.save_signal({
                    "symbol": symbol,
                    "signal": sig,
                    "strategy": strategy.name,
                    "price": last.get("price", 0),
                })
        except Exception as e:
            logger.error(f"Sinyal hatası [{strategy.name}/{symbol}]: {e}", exc_info=True)
            signals[strategy.name] = "HOLD"

    # ── 2. Sinyalleri uzlaştır ─────────────────────────────────────────────
    decision, agreeing_strategies, is_strong = _resolve_signals(signals)

    buy_list  = [s for s, v in signals.items() if v == "BUY"]
    sell_list = [s for s, v in signals.items() if v == "SELL"]

    # ── Sembol özet logu (her sembol için daima yazılır) ──────────────────
    sig_summary = " | ".join(f"{s}:{v}" for s, v in signals.items())
    logger.info(f"[{symbol}] Sinyaller → {sig_summary}")

    if buy_list and sell_list:
        logger.info(
            f"[{symbol}] ✗ İşlem yok — Çelişkili sinyal (BUY:{buy_list} vs SELL:{sell_list})"
        )
        return _no_trade("HOLD")

    if decision == "HOLD":
        logger.info(f"[{symbol}] ✗ İşlem yok — Tüm stratejiler HOLD")
        return _no_trade("HOLD")

    strength_label = "GÜÇLÜ" if is_strong else "normal"
    logger.info(
        f"[{symbol}] {decision} sinyali ({strength_label}) ← [{agreeing_strategies}]"
    )

    # ── IBKR gerçek pozisyon / aktif emir kontrolü ────────────────────────
    # ib.positions() + ib.openTrades() doğrudan sorgulanır; shadow listeye
    # güvenilmez. Döngü aralarında dışarıdan açılmış pozisyonları da yakalar.
    clean = symbol.split(".")[0]   # yfinance suffix varsa çıkar (EU: "EXW1.DE" → "EXW1")
    if _ibkr_symbol_has_position(ibkr_client, clean):
        logger.info(
            f"[{symbol}] ✗ İşlem yok — IBKR'de zaten pozisyon/emir var"
        )
        return _no_trade(decision)

    entry_price = float(df["close"].iloc[-1])

    # ── 3. Risk değerlendirmesi ────────────────────────────────────────────
    risk_result = risk_manager.evaluate(
        signal=decision,
        symbol=symbol,
        entry_price=entry_price,
        df=df,
        currency=currency,
        market=market,
    )

    if not risk_result["approved"]:
        logger.info(f"[{symbol}] ✗ İşlem yok — Risk reddetti: {risk_result['reason']}")
        return _no_trade(decision)

    # ── 4. Kontrat oluştur ─────────────────────────────────────────────────
    if market == "BVB":
        contract = ibkr_client.get_bvb_contract(symbol)
    elif market == "US":
        contract = ibkr_client.get_us_contract(symbol)
    elif market == "FOREX":
        contract = ibkr_client.get_forex_contract(symbol[:3], symbol[3:])
    elif market == "EU":
        contract = ibkr_client.get_eu_contract(symbol, exchange)
    else:
        contract = ibkr_client.get_bist_contract(symbol)

    # ── 5. Emir gönder ────────────────────────────────────────────────────
    if IS_PAPER_TRADING:
        logger.info(
            f"[PAPER] {decision} | {symbol} @ {entry_price:.4f} | "
            f"Adet={risk_result['quantity']} | "
            f"SL={risk_result['stop_loss']} | TP={risk_result['take_profit']} | "
            f"{'⭐ GÜÇLÜ SİNYAL' if is_strong else ''}"
        )

    try:
        order_manager.place_bracket_order(
            action=decision,
            contract=contract,
            quantity=risk_result["quantity"],
            entry_price=entry_price,
            stop_loss=risk_result["stop_loss"],
            take_profit=risk_result["take_profit"],
        )
    except Exception as e:
        logger.error(f"Emir hatası [{symbol}]: {e}", exc_info=True)
        notifier.send_error(f"Emir Hatası: {symbol}", str(e))
        return _no_trade(decision)

    # ── 6. Kayıt ve bildirim ──────────────────────────────────────────────
    db.save_trade({
        "symbol": symbol,
        "direction": decision,
        "entry_price": entry_price,
        "stop_loss": risk_result["stop_loss"],
        "take_profit": risk_result["take_profit"],
        "quantity": risk_result["quantity"],
        "currency": currency,
        "strategy": agreeing_strategies,
        "status": "OPEN",
    })

    risk_manager.add_position({
        "symbol": symbol,
        "direction": decision,
        "entry": entry_price,
    })

    notifier.send_trade_opened(
        symbol=symbol,
        direction=decision,
        entry_price=entry_price,
        stop_loss=risk_result["stop_loss"],
        take_profit=risk_result["take_profit"],
        quantity=risk_result["quantity"],
        strategy=f"{'⭐ ' if is_strong else ''}{agreeing_strategies}",
        currency=currency,
    )

    return {"signal": decision, "traded": True}


# ── Ana Bot Döngüsü ────────────────────────────────────────────────────────

def _rebuild_positions_from_ibkr(
    ibkr_client: IBKRClient,
    risk_manager: RiskManager,
    db: Database,
) -> None:
    """
    ib.positions() tek gerçek kaynak. risk_manager.open_positions sıfırdan yeniden
    oluşturulur — diff-patch yapılmaz.

    Startup'ta ve her döngü başında çağrılır.
    Önceki listede olup artık IBKR'de olmayan semboller DB'de CLOSED olarak işaretlenir.
    """
    if not ibkr_client.connected:
        return

    # ── Gerçek pozisyonlar: ib.positions() ile position != 0 olanlar ──────
    new_positions: list[dict] = []
    try:
        ibkr_positions = ibkr_client.ib.positions()
        active_symbols = {p.contract.symbol for p in ibkr_positions if p.position != 0}

        for pos in ibkr_positions:
            if pos.position == 0:
                continue
            new_positions.append({
                "symbol":    pos.contract.symbol,
                "direction": "BUY" if pos.position > 0 else "SELL",
                "entry":     pos.avgCost,
                "source":    "ibkr_position",
            })
    except Exception as e:
        logger.warning(f"[Rebuild] ib.positions() hatası: {e}")
        return  # Veri gelmiyorsa mevcut listeyi koru, listeyi silme

    # ── Henüz dolmamış bracket parent emirleri de "açık" sayılır ─────────
    # (parent BUY Submitted ama henüz Filled değil — ib.positions()'da görünmez)
    try:
        ibkr_client.ib.reqOpenOrders()
        for trade in ibkr_client.ib.openTrades():
            if trade.order.parentId != 0:
                continue  # child SL/TP, atla
            if trade.orderStatus.status not in ("Submitted", "PreSubmitted"):
                continue
            symbol = trade.contract.symbol
            if symbol not in active_symbols:
                active_symbols.add(symbol)
                new_positions.append({
                    "symbol":    symbol,
                    "direction": trade.order.action,
                    "entry":     trade.order.lmtPrice,
                    "source":    "ibkr_pending_order",
                })
    except Exception as e:
        logger.warning(f"[Rebuild] ib.openTrades() hatası: {e}")

    # ── DB: kapanmış pozisyonları kapat ───────────────────────────────────
    old_symbols = {p["symbol"] for p in risk_manager.open_positions}
    new_symbols  = {p["symbol"] for p in new_positions}

    for symbol in old_symbols - new_symbols:
        try:
            db.close_open_trade_by_symbol(symbol)
        except Exception as e:
            logger.warning(f"[Rebuild] DB kapatma hatası [{symbol}]: {e}")
        logger.info(f"[Rebuild] Kapandı (IBKR'de yok — SL/TP veya manuel): {symbol}")

    for symbol in new_symbols - old_symbols:
        logger.info(f"[Rebuild] Eklendi (IBKR'de mevcut): {symbol}")

    risk_manager.open_positions = new_positions
    logger.info(
        f"[Rebuild] {len(new_positions)} açık pozisyon"
        + (f": {sorted(new_symbols)}" if new_symbols else " — boş")
    )


def _ibkr_symbol_has_position(ibkr_client: IBKRClient, symbol: str) -> bool:
    """
    Emir göndermeden hemen önce IBKR'yi doğrudan sorgular.

    Adım 1 — primary: ib.positions() listesinden position != 0 olan semboller
              kümesi oluşturulur; sembol bu kümede varsa True döner.
    Adım 2 — fallback: dolmamış bracket parent emirleri (BUY Submitted ama
              henüz Filled değil) için ib.openTrades() kontrol edilir.

    Args:
        symbol: Suffix olmadan temiz sembol (örn: "AAPL", "EXW1", "VEUR")

    Returns:
        bool: Aktif pozisyon veya bekleyen emir varsa True
    """
    if not ibkr_client.connected:
        return False

    # Adım 1 — ib.positions(): position != 0 → sembol kümesi
    try:
        aktif_pozisyonlar = {
            p.contract.symbol
            for p in ibkr_client.ib.positions()
            if p.position != 0
        }
        if symbol in aktif_pozisyonlar:
            logger.debug(f"[PosCheck] {symbol} ib.positions()'da mevcut — işlem açılmıyor")
            return True
    except Exception as e:
        logger.warning(f"[PosCheck] positions() hatası [{symbol}]: {e}")

    # Adım 2 — ib.openTrades(): dolmamış bracket parent emir
    try:
        for trade in ibkr_client.ib.openTrades():
            if trade.contract.symbol != symbol:
                continue
            if trade.order.parentId != 0:
                continue  # child SL/TP, atla
            if trade.orderStatus.status in ("Submitted", "PreSubmitted"):
                logger.debug(
                    f"[PosCheck] {symbol} için bekleyen bracket emir var — işlem açılmıyor"
                )
                return True
    except Exception as e:
        logger.warning(f"[PosCheck] openTrades() hatası [{symbol}]: {e}")

    return False


def main():
    global _running

    mode = "PAPER TRADING" if IS_PAPER_TRADING else "CANLI TRADING"
    logger.info(f"{'='*50}")
    logger.info(f"Trading Bot başlatılıyor — Mod: {mode}")
    logger.info(f"{'='*50}")

    # ── Bileşenleri Başlat ─────────────────────────────────────────────────
    ibkr_client = IBKRClient()
    db = Database()
    notifier = TelegramNotifier()
    risk_manager = RiskManager(capital=10_000.0)

    # IBKR bağlantısı (canlı veri için gerekli, paper modda opsiyonel)
    connected = ibkr_client.connect()
    if not connected:
        logger.warning("IBKR bağlantısı kurulamadı. yfinance ile devam ediliyor.")

    fetcher = DataFetcher(ibkr_client=ibkr_client if connected else None)
    order_manager = OrderManager(ibkr_client)

    # ── Callback tanımları (closure — db'yi yakalar) ───────────────────────
    def _on_portfolio_update(item):
        """
        IBKR her portföy güncellemesinde tetiklenir.
        unrealizedPNL → DB'deki açık pozisyonun pnl alanına yazılır.
        unrealizedPNL → DB'ye yazılır; ayrı bir account summary isteği gerekmez.
        """
        symbol = item.contract.symbol
        upnl = item.unrealizedPNL
        if upnl is None or upnl != upnl:   # None / NaN kontrolü
            return
        with db._connect() as conn:
            conn.execute(
                "UPDATE trades SET pnl = ? WHERE symbol LIKE ? AND status = 'OPEN'",
                (float(upnl), f"%{symbol}%"),
            )

    def _register_ibkr_callbacks():
        """
        Bağlantı kurulduğunda ve her yeniden bağlanmada çağrılır.
        -= ile önce çıkar, tekrar += ile ekle: çift kayıt önlenir.
        """
        try:
            ibkr_client.ib.updatePortfolioEvent -= _on_portfolio_update
        except Exception:
            pass
        ibkr_client.ib.updatePortfolioEvent += _on_portfolio_update
        logger.info("IBKR callback'leri kaydedildi (updatePortfolioEvent).")

    if connected:
        _register_ibkr_callbacks()

    # ── Başlangıç: IBKR'den gerçek pozisyonları yükle ─────────────────────
    _rebuild_positions_from_ibkr(ibkr_client, risk_manager, db)

    # ── Stratejileri Yükle ─────────────────────────────────────────────────
    strategies = [
        RSIMACDStrategy(),
        BollingerStrategy(),
        TrendStrategy(params={"timeframe": "1h"}),
    ]

    notifier.send_bot_status("STARTED", f"Mod: {mode}")
    logger.info(f"Aktif stratejiler: {[s.name for s in strategies]}")

    # ── Ana Döngü ──────────────────────────────────────────────────────────
    scan_interval = 60 * 15  # Her 15 dakikada bir tara

    while _running:
        try:
            loop_start = datetime.now()

            # ── Bağlantı kontrolü: Error 1100 / kopma → otomatik yeniden bağlan
            if not ibkr_client.is_connected():
                logger.warning(
                    "[IBKR] Bağlantı koptu. 30 saniye sonra yeniden deneniyor..."
                )
                for _ in range(30):
                    if not _running:
                        break
                    time.sleep(1)
                if not _running:
                    break

                connected = ibkr_client.connect()
                if connected:
                    _register_ibkr_callbacks()
                    _rebuild_positions_from_ibkr(ibkr_client, risk_manager, db)
                    fetcher.ibkr = ibkr_client   # fetcher'a güncel client'ı ver
                    logger.info("[IBKR] Yeniden bağlantı başarılı.")
                    notifier.send_bot_status("RECONNECTED", "IBKR bağlantısı yeniden kuruldu.")
                else:
                    logger.warning("[IBKR] Yeniden bağlantı başarısız, yfinance ile devam.")
                continue  # Bu döngü iterasyonunu atla, pozisyon listesi hazır değil

            any_market_open = False

            # ── IBKR pozisyon listesini sıfırdan yeniden oluştur ──────────
            # ib.positions() + ib.openTrades() tek gerçek kaynak; shadow
            # liste diff-patch yapılmaz, tamamen yeniden yazılır.
            _rebuild_positions_from_ibkr(ibkr_client, risk_manager, db)

            # Her döngüde açık pozisyon durumunu logla
            open_count = len(risk_manager.open_positions)
            open_symbols = [p.get("symbol") for p in risk_manager.open_positions]
            logger.info(
                f"Açık pozisyon: {open_count}/{MAX_OPEN_POSITIONS} "
                + (f"— {open_symbols}" if open_symbols else "— yok")
            )

            # BVB Sembolleri — devre dışı, ileride aktif edilecek
            # if is_market_open("BVB"):
            #     for symbol in BVB_SYMBOLS: ...

            # Avrupa ETF Sembolleri (10:00-18:30 CET — Frankfurt, Paris, Amsterdam)
            if is_market_open("EU"):
                any_market_open = True
                logger.info(f"EU piyasası açık — {len(EU_SYMBOLS)} sembol taranıyor...")
                signal_count = 0
                trade_count = 0
                for symbol, exch in EU_EXCHANGE_MAP.items():
                    # IBKR kontrolü için yfinance suffix'ini çıkar (örn: "EXW1.DE" → "EXW1")
                    clean_symbol = symbol.split(".")[0]
                    if connected and not ibkr_client.symbol_exists_ibkr(clean_symbol):
                        logger.info(
                            f"[EU] {clean_symbol} IBKR'de bulunamadı ({exch}), atlanıyor."
                        )
                        continue
                    result = run_strategies_for_symbol(
                        symbol, "EU", fetcher, strategies,
                        risk_manager, order_manager, ibkr_client, db, notifier,
                        exchange=exch,
                    )
                    if result["signal"] != "HOLD":
                        signal_count += 1
                    if result["traded"]:
                        trade_count += 1
                logger.info(
                    f"EU tarama tamamlandı — {len(EU_SYMBOLS)} sembol | "
                    f"Sinyal: {signal_count} | İşlem açıldı: {trade_count} | "
                    f"Açık pozisyon: {len(risk_manager.open_positions)}/{MAX_OPEN_POSITIONS}"
                )

            # BIST Sembolleri — devre dışı, ileride aktif edilecek
            # if is_market_open("BIST"):
            #     for symbol in BIST_SYMBOLS: ...

            # ABD Sembolleri (SMART routing, 09:30-16:00 EST)
            if is_market_open("US"):
                any_market_open = True
                logger.info(f"US piyasası açık — {len(US_SYMBOLS)} sembol taranıyor...")
                signal_count = 0
                trade_count = 0
                for symbol in US_SYMBOLS:
                    result = run_strategies_for_symbol(
                        symbol, "US", fetcher, strategies,
                        risk_manager, order_manager, ibkr_client, db, notifier,
                    )
                    if result["signal"] != "HOLD":
                        signal_count += 1
                    if result["traded"]:
                        trade_count += 1
                logger.info(
                    f"US tarama tamamlandı — {len(US_SYMBOLS)} sembol | "
                    f"Sinyal: {signal_count} | İşlem açıldı: {trade_count} | "
                    f"Açık pozisyon: {len(risk_manager.open_positions)}/{MAX_OPEN_POSITIONS}"
                )

            # Forex (24/5 — IDEALPRO)
            if is_market_open("FOREX"):
                any_market_open = True
                for base, quote in FOREX_PAIRS:
                    symbol = f"{base}{quote}"
                    run_strategies_for_symbol(
                        symbol, "FOREX", fetcher, strategies,
                        risk_manager, order_manager, ibkr_client, db, notifier,
                    )

            if not any_market_open:
                logger.debug("Tüm piyasalar kapalı, bekleniyor...")

            # Günlük özet (saat 18:35'te gönder)
            now = datetime.now()
            if now.hour == 18 and 35 <= now.minute < 36:
                stats = db.get_stats()
                notifier.send_daily_summary(
                    total_pnl=stats["total_pnl"],
                    open_positions=len(risk_manager.open_positions),
                    win_count=stats["win_count"],
                    loss_count=stats["loss_count"],
                )
                db.upsert_daily_summary({
                    "total_pnl": stats["total_pnl"],
                    "win_count": stats["win_count"],
                    "loss_count": stats["loss_count"],
                    "open_positions": len(risk_manager.open_positions),
                })

            # Sonraki döngüye kadar bekle
            elapsed = (datetime.now() - loop_start).total_seconds()
            sleep_time = max(0, scan_interval - elapsed)
            logger.debug(f"Sonraki tarama: {sleep_time:.0f} saniye sonra")

            # Küçük aralıklarla kontrol ederek _running bayrağına duyarlı ol
            for _ in range(int(sleep_time)):
                if not _running:
                    break
                time.sleep(1)

        except Exception as e:
            logger.critical(f"Ana döngü hatası: {e}", exc_info=True)
            notifier.send_error("Ana Döngü Hatası", str(e))
            time.sleep(30)  # Hata sonrası kısa bekleme

    # ── Temiz Kapatma ──────────────────────────────────────────────────────
    logger.info("Bot kapatılıyor...")
    notifier.send_bot_status("STOPPED", "Kullanıcı tarafından durduruldu.")
    ibkr_client.disconnect()
    logger.info("Bot durduruldu.")


if __name__ == "__main__":
    main()
