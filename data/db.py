"""
data/db.py
----------
SQLite veritabanı işlemleri. Üç tablo yönetir:
  - trades: Gerçekleşen işlem geçmişi
  - signals: Strateji sinyalleri (acted_on: işleme alındı mı?)
  - daily_summary: Günlük P&L ve istatistikler

Kullanım:
    db = Database()
    db.save_trade({...})
    trades = db.get_trades(symbol="TLV")
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

# db.py'nin bulunduğu dizinden bir üst klasördeki data/ altında trading.db
DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "trading.db")
)


class Database:
    """SQLite veritabanı yönetim sınıfı."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

        # :memory: kullanılıyorsa bağlantıyı kalıcı sakla —
        # in-memory DB bağlantı kapanınca silinir.
        if db_path == ":memory:":
            self.conn = sqlite3.connect(":memory:")
            self.conn.row_factory = sqlite3.Row
            conn = self.conn
        else:
            self.conn = None
            conn = sqlite3.connect(self.db_path)

        try:
            cursor = conn.cursor()

            # trades tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT NOT NULL,
                    direction   TEXT NOT NULL,       -- BUY / SELL
                    entry_price REAL NOT NULL,
                    exit_price  REAL,
                    stop_loss   REAL,
                    take_profit REAL,
                    quantity    INTEGER NOT NULL,
                    pnl         REAL DEFAULT 0,
                    currency    TEXT NOT NULL,
                    strategy    TEXT,
                    status      TEXT DEFAULT 'OPEN', -- OPEN / CLOSED
                    opened_at   TEXT NOT NULL,
                    closed_at   TEXT
                )
            """)

            # signals tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol     TEXT NOT NULL,
                    signal     TEXT NOT NULL,       -- BUY / SELL / HOLD
                    strategy   TEXT NOT NULL,
                    timeframe  TEXT,
                    price      REAL,
                    created_at TEXT NOT NULL,
                    acted_on   INTEGER DEFAULT 0   -- 0: hayır, 1: evet
                )
            """)

            # daily_summary tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    date           TEXT NOT NULL UNIQUE,
                    total_pnl      REAL DEFAULT 0,
                    win_count      INTEGER DEFAULT 0,
                    loss_count     INTEGER DEFAULT 0,
                    open_positions INTEGER DEFAULT 0,
                    updated_at     TEXT NOT NULL
                )
            """)

            conn.commit()
            logger.info(f"Veritabanı hazır: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Tablo oluşturma hatası: {e}")
            raise
        finally:
            # in-memory bağlantıyı kapatma — dosya bağlantısını kapat
            if self.conn is None:
                conn.close()

    # ── Bağlantı Yönetimi ─────────────────────────────────────────────────

    @contextmanager
    def _connect(self):
        """
        Context manager ile SQLite bağlantısı sağlar.

        :memory: modunda self.conn kalıcı bağlantıyı yeniden kullanır,
        kapatmaz. Dosya modunda her işlem için yeni bağlantı açar/kapatır.
        """
        if self.conn is not None:
            # in-memory: mevcut bağlantıyı kullan, kapatma
            try:
                yield self.conn
                self.conn.commit()
            except sqlite3.Error as e:
                self.conn.rollback()
                logger.error(f"Veritabanı hatası: {e}")
                raise
        else:
            # Dosya tabanlı: yeni bağlantı aç, işlem sonrası kapat
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                yield conn
                conn.commit()
            except sqlite3.Error as e:
                if conn:
                    conn.rollback()
                logger.error(f"Veritabanı hatası: {e}")
                raise
            finally:
                if conn:
                    conn.close()

    # ── Trade CRUD ────────────────────────────────────────────────────────

    def save_trade(self, trade: dict) -> int:
        """
        Yeni işlem kaydeder.

        Args:
            trade: İşlem bilgileri dict'i

        Returns:
            int: Oluşturulan kayıt ID'si
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades
                    (symbol, direction, entry_price, exit_price, stop_loss,
                     take_profit, quantity, pnl, currency, strategy, status, opened_at, closed_at)
                VALUES
                    (:symbol, :direction, :entry_price, :exit_price, :stop_loss,
                     :take_profit, :quantity, :pnl, :currency, :strategy, :status,
                     :opened_at, :closed_at)
            """, {
                "symbol": trade.get("symbol"),
                "direction": trade.get("direction"),
                "entry_price": trade.get("entry_price"),
                "exit_price": trade.get("exit_price"),
                "stop_loss": trade.get("stop_loss"),
                "take_profit": trade.get("take_profit"),
                "quantity": trade.get("quantity"),
                "pnl": trade.get("pnl", 0),
                "currency": trade.get("currency", "USD"),
                "strategy": trade.get("strategy", ""),
                "status": trade.get("status", "OPEN"),
                "opened_at": trade.get("opened_at", datetime.now().isoformat()),
                "closed_at": trade.get("closed_at"),
            })
            trade_id = cursor.lastrowid
            logger.info(f"Trade kaydedildi: #{trade_id} {trade.get('symbol')}")
            return trade_id

    def update_open_trade_pnl(self, symbol: str, unrealized_pnl: float):
        """
        IBKR updatePortfolioEvent callback'inden gelen unrealizedPNL değerini
        açık pozisyonun pnl alanına yazar.

        Args:
            symbol: Hisse sembolü
            unrealized_pnl: IBKR'den gelen anlık unrealized P&L
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE trades SET pnl = ? WHERE symbol = ? AND status = 'OPEN'",
                (unrealized_pnl, symbol),
            )
            logger.debug(f"Unrealized PNL güncellendi: {symbol} = {unrealized_pnl:.2f}")

    def close_open_trade_by_symbol(self, symbol: str):
        """
        Açık bir pozisyonu sembol üzerinden kapatır.
        IBKR senkronizasyonunda kullanılır: pozisyon artık TWS'te yoksa
        (SL/TP tetiklendi veya manuel kapatıldı) DB'yi günceller.
        exit_price bilinmediğinden güncellenmez; pnl alanı son IBKR
        portfolio callback'inden gelen değeri korur.

        Args:
            symbol: Kapatılacak pozisyonun sembolü
        """
        with self._connect() as conn:
            conn.execute("""
                UPDATE trades
                SET status = 'CLOSED', closed_at = ?
                WHERE symbol = ? AND status = 'OPEN'
            """, (datetime.now().isoformat(), symbol))
            logger.info(f"Trade sembol ile kapatıldı (sync): {symbol}")

    def close_trade(self, trade_id: int, exit_price: float, pnl: float):
        """
        İşlemi kapatır.

        Args:
            trade_id: İşlem ID'si
            exit_price: Çıkış fiyatı
            pnl: Kâr/zarar
        """
        with self._connect() as conn:
            conn.execute("""
                UPDATE trades
                SET exit_price = ?, pnl = ?, status = 'CLOSED', closed_at = ?
                WHERE id = ?
            """, (exit_price, pnl, datetime.now().isoformat(), trade_id))
            logger.info(f"Trade kapatıldı: #{trade_id} | P&L={pnl:.2f}")

    def get_trades(
        self,
        symbol: str = None,
        strategy: str = None,
        status: str = None,
        limit: int = 100,
    ) -> List[dict]:
        """
        İşlem geçmişini filtreli getirir.

        Args:
            symbol: Sembol filtresi (opsiyonel)
            strategy: Strateji filtresi (opsiyonel)
            status: Durum filtresi ("OPEN", "CLOSED")
            limit: Maksimum kayıt sayısı

        Returns:
            list: İşlem listesi
        """
        query = "SELECT * FROM trades WHERE 1=1"
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if strategy:
            query += " AND strategy = ?"
            params.append(strategy)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY opened_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_open_trades(self) -> List[dict]:
        """Açık pozisyonları döndürür."""
        return self.get_trades(status="OPEN")

    # ── Signal CRUD ───────────────────────────────────────────────────────

    def save_signal(self, signal: dict) -> int:
        """Strateji sinyali kaydeder."""
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO signals (symbol, signal, strategy, timeframe, price, created_at, acted_on)
                VALUES (:symbol, :signal, :strategy, :timeframe, :price, :created_at, :acted_on)
            """, {
                "symbol": signal.get("symbol"),
                "signal": signal.get("signal"),
                "strategy": signal.get("strategy"),
                "timeframe": signal.get("timeframe", ""),
                "price": signal.get("price", 0),
                "created_at": signal.get("created_at", datetime.now().isoformat()),
                "acted_on": int(signal.get("acted_on", False)),
            })
            return cursor.lastrowid

    def mark_signal_acted(self, signal_id: int):
        """Sinyalin işleme alındığını işaretler."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE signals SET acted_on = 1 WHERE id = ?", (signal_id,)
            )

    # ── Daily Summary ─────────────────────────────────────────────────────

    def upsert_daily_summary(self, summary: dict):
        """
        Günlük özeti oluşturur veya günceller.

        Args:
            summary: {"date": "2024-01-15", "total_pnl": 250.0, ...}
        """
        today = summary.get("date", date.today().isoformat())
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO daily_summary (date, total_pnl, win_count, loss_count, open_positions, updated_at)
                VALUES (:date, :total_pnl, :win_count, :loss_count, :open_positions, :updated_at)
                ON CONFLICT(date) DO UPDATE SET
                    total_pnl = excluded.total_pnl,
                    win_count = excluded.win_count,
                    loss_count = excluded.loss_count,
                    open_positions = excluded.open_positions,
                    updated_at = excluded.updated_at
            """, {
                "date": today,
                "total_pnl": summary.get("total_pnl", 0),
                "win_count": summary.get("win_count", 0),
                "loss_count": summary.get("loss_count", 0),
                "open_positions": summary.get("open_positions", 0),
                "updated_at": datetime.now().isoformat(),
            })

    def get_daily_summaries(self, days: int = 30) -> List[dict]:
        """Son N günün özetini döndürür."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM daily_summary ORDER BY date DESC LIMIT ?", (days,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Genel istatistikleri hesaplar."""
        with self._connect() as conn:
            # Toplam P&L
            total_pnl = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='CLOSED'"
            ).fetchone()[0]

            # Win/loss sayısı
            win_count = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status='CLOSED' AND pnl > 0"
            ).fetchone()[0]
            loss_count = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status='CLOSED' AND pnl <= 0"
            ).fetchone()[0]

            total = win_count + loss_count

            return {
                "total_pnl": round(total_pnl, 2),
                "total_trades": total,
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate": round(win_count / total * 100, 2) if total > 0 else 0,
            }
