"""
data/fetcher.py
---------------
Piyasa verisi çekme modülü. İki kaynaktan veri destekler:
  1. IBKR TWS API — canlı ve geçmiş bar verisi
  2. yfinance — backtest için geçmiş veri (BVB suffix yok, BIST için .IS)

Desteklenen timeframe'ler: 1m, 5m, 15m, 1h, 1d
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from ib_insync import Contract

from config.settings import TIMEFRAMES

logger = logging.getLogger(__name__)


class DataFetcher:
    """Canlı ve geçmiş piyasa verisi çeken sınıf."""

    def __init__(self, ibkr_client=None):
        """
        Args:
            ibkr_client: IBKRClient instance (canlı veri için gerekli)
        """
        self.ibkr = ibkr_client

    # ── IBKR Veri Çekme ───────────────────────────────────────────────────

    def get_historical_bars_ibkr(
        self,
        contract: Contract,
        duration: str = "5 D",
        bar_size: str = "1 hour",
        what_to_show: str = "TRADES",
    ) -> Optional[pd.DataFrame]:
        """
        IBKR'den geçmiş bar verisi çeker.

        Args:
            contract: IBKR kontrat objesi
            duration: Veri süresi (örn: "5 D", "1 M", "1 Y")
            bar_size: Bar boyutu (örn: "1 min", "5 mins", "1 hour", "1 day")
            what_to_show: Veri tipi ("TRADES", "MIDPOINT", "BID", "ASK")

        Returns:
            DataFrame: open, high, low, close, volume sütunları
        """
        if not self.ibkr or not self.ibkr.is_connected():
            logger.error("IBKR bağlantısı yok, geçmiş veri çekilemiyor.")
            return None

        try:
            bars = self.ibkr.ib.reqHistoricalData(
                contract=contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=True,
                formatDate=1,
            )

            if not bars:
                logger.warning(f"Veri bulunamadı: {contract.symbol}")
                return None

            # DataFrame'e dönüştür
            df = pd.DataFrame(
                {
                    "datetime": [b.date for b in bars],
                    "open": [b.open for b in bars],
                    "high": [b.high for b in bars],
                    "low": [b.low for b in bars],
                    "close": [b.close for b in bars],
                    "volume": [b.volume for b in bars],
                }
            )
            df.set_index("datetime", inplace=True)
            logger.info(
                f"IBKR'den {len(df)} bar çekildi: {contract.symbol} [{bar_size}]"
            )
            return df

        except Exception as e:
            logger.error(f"IBKR geçmiş veri hatası [{contract.symbol}]: {e}")
            return None

    def get_live_bar_ibkr(self, contract: Contract) -> Optional[dict]:
        """
        IBKR'den anlık fiyat bilgisi çeker.

        Args:
            contract: IBKR kontrat objesi

        Returns:
            dict: last, bid, ask, volume
        """
        if not self.ibkr or not self.ibkr.is_connected():
            logger.error("IBKR bağlantısı yok.")
            return None

        try:
            ticker = self.ibkr.ib.reqMktData(contract, "", False, False)
            self.ibkr.ib.sleep(1)  # Veri gelmesi için bekle

            return {
                "last": ticker.last,
                "bid": ticker.bid,
                "ask": ticker.ask,
                "volume": ticker.volume,
                "timestamp": datetime.now(),
            }
        except Exception as e:
            logger.error(f"Canlı veri hatası [{contract.symbol}]: {e}")
            return None

    # ── yfinance Veri Çekme ───────────────────────────────────────────────

    def get_historical_yfinance(
        self,
        symbol: str,
        market: str = "BVB",
        period: str = "1y",
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """
        yfinance ile geçmiş veri çeker. Backtest için kullanılır.

        BVB sembolleri: suffix yok (örn: "TLV")
        BIST sembolleri: .IS suffix (örn: "THYAO.IS")
        EU sembolleri: yfinance suffix ile gelir, olduğu gibi gönderilir (örn: "EXW1.DE", "VEUR.AS")

        Args:
            symbol: Hisse sembolü
            market: "BVB", "BIST", "EU" veya "FOREX"
            period: Veri periyodu ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y")
            interval: Bar aralığı ("1m", "5m", "15m", "1h", "1d")

        Returns:
            DataFrame: OHLCV verisi
        """
        try:
            # Sembol formatını ayarla
            ticker_symbol = self._format_yfinance_symbol(symbol, market)

            logger.info(
                f"yfinance veri çekiliyor: {ticker_symbol} [{interval}] [{period}]"
            )

            ticker = yf.Ticker(ticker_symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"yfinance'den veri gelmedi: {ticker_symbol}")
                return None

            # Sütun isimlerini standartlaştır
            df.columns = [c.lower() for c in df.columns]
            df.index.name = "datetime"

            logger.info(f"yfinance'den {len(df)} bar çekildi: {ticker_symbol}")
            return df

        except Exception as e:
            logger.error(f"yfinance veri hatası [{symbol}]: {e}")
            return None

    def get_multiple_symbols_yfinance(
        self,
        symbols: list,
        market: str = "BVB",
        period: str = "1y",
        interval: str = "1d",
    ) -> dict:
        """
        Birden fazla sembol için toplu veri çeker.

        Args:
            symbols: Sembol listesi
            market: Piyasa adı
            period: Veri periyodu
            interval: Bar aralığı

        Returns:
            dict: {symbol: DataFrame} eşleşmesi
        """
        result = {}
        for symbol in symbols:
            df = self.get_historical_yfinance(symbol, market, period, interval)
            if df is not None:
                result[symbol] = df
        return result

    # ── Yardımcı Metodlar ─────────────────────────────────────────────────

    def _format_yfinance_symbol(self, symbol: str, market: str) -> str:
        """
        yfinance için sembol formatını düzenler.

        Args:
            symbol: Ham sembol adı
            market: Piyasa adı

        Returns:
            str: Formatlanmış sembol
        """
        if market == "BIST":
            # Sembol zaten .IS içeriyorsa tekrar ekleme (örn: "THYAO.IS")
            return symbol if symbol.endswith(".IS") else f"{symbol}.IS"
        elif market == "FOREX":
            # Forex için =X suffix (örn: "EURUSD=X")
            return f"{symbol}=X"
        elif market == "EU":
            # EU sembolleri zaten yfinance suffix içeriyor (örn: "EXW1.DE", "VEUR.AS", "CSPX.L")
            return symbol
        else:
            # BVB için sembol zaten .RO suffix içeriyor (örn: TLV.RO)
            return symbol

    def timeframe_to_ibkr(self, timeframe: str) -> str:
        """Timeframe stringini IBKR formatına çevirir."""
        return TIMEFRAMES.get(timeframe, "1 hour")

    def timeframe_to_yfinance(self, timeframe: str) -> str:
        """Timeframe stringini yfinance formatına çevirir."""
        mapping = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "1h": "1h",
            "1d": "1d",
        }
        return mapping.get(timeframe, "1d")
