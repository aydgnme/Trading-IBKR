"""
broker/ibkr_client.py
---------------------
IBKR TWS/IB Gateway bağlantısını yöneten modül.
ib_insync kütüphanesi kullanılarak bağlantı kurulur, retry mantığı
ve sembol formatları burada tanımlanır.

Kullanım:
    client = IBKRClient()
    client.connect()
    # ... işlemler ...
    client.disconnect()
"""

import time
import logging
from ib_insync import IB, Stock, Forex, Contract

from config.settings import IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, IS_PAPER_TRADING

logger = logging.getLogger(__name__)

# Paper trading ve gerçek trading portları
PAPER_PORT = 7497
LIVE_PORT = 7496


class IBKRClient:
    """IBKR bağlantısını yöneten ana sınıf."""

    def __init__(self, client_id: int = None):
        """
        Args:
            client_id: IBKR client ID. Belirtilmezse .env'deki IBKR_CLIENT_ID kullanılır.
                       Test bağlantıları için 2 geçin — main.py'nin clientId=1 ile çakışmaz.
        """
        self.ib = IB()
        self.host = IBKR_HOST
        # Paper/gerçek trading moduna göre port seç
        self.port = PAPER_PORT if IS_PAPER_TRADING else LIVE_PORT
        self.client_id = client_id if client_id is not None else IBKR_CLIENT_ID
        self.connected = False

    def connect(self, max_retries: int = 3, retry_delay: int = 5) -> bool:
        """
        TWS/IB Gateway'e bağlanır. Başarısız olursa max_retries kadar tekrar dener.

        Args:
            max_retries: Maksimum yeniden deneme sayısı
            retry_delay: Denemeler arasındaki bekleme süresi (saniye)

        Returns:
            bool: Bağlantı başarılıysa True
        """
        mode = "PAPER" if IS_PAPER_TRADING else "LIVE"
        logger.info(f"IBKR bağlantısı deneniyor [{mode}] {self.host}:{self.port}")

        for attempt in range(1, max_retries + 1):
            try:
                self.ib.connect(
                    host=self.host,
                    port=self.port,
                    clientId=self.client_id,
                    timeout=20,
                    readonly=False,
                )
                self.connected = True
                logger.info(f"IBKR bağlantısı başarılı (deneme {attempt}/{max_retries})")
                return True

            except Exception as e:
                logger.warning(
                    f"Bağlantı denemesi {attempt}/{max_retries} başarısız: {e}"
                )
                if attempt < max_retries:
                    logger.info(f"{retry_delay} saniye sonra tekrar deneniyor...")
                    time.sleep(retry_delay)

        logger.error("IBKR bağlantısı kurulamadı, tüm denemeler tükendi.")
        self.connected = False
        return False

    def disconnect(self):
        """IBKR bağlantısını kapatır."""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            logger.info("IBKR bağlantısı kapatıldı.")

    def is_connected(self) -> bool:
        """Bağlantının aktif olup olmadığını kontrol eder."""
        return self.ib.isConnected()

    # ── Kontrat Oluşturucular ──────────────────────────────────────────────

    def get_bvb_contract(self, symbol: str) -> Stock:
        """
        BVB (Bükreş Borsası) için kontrat oluşturur.
        Format: STOCK, exchange="BVB", currency="RON"

        Args:
            symbol: Sembol — .RO suffix varsa otomatik çıkarılır (örn: "TLV.RO" → "TLV")
        """
        clean = symbol.removesuffix(".RO")
        return Stock(symbol=clean, exchange="BVB", currency="RON")

    def get_bist_contract(self, symbol: str) -> Stock:
        """
        BIST (Borsa İstanbul) için kontrat oluşturur.
        Format: STOCK, exchange="IBIS", currency="TRY"

        Args:
            symbol: Sembol — .IS suffix varsa otomatik çıkarılır (örn: "GARAN.IS" → "GARAN")
        """
        clean = symbol.removesuffix(".IS")
        return Stock(symbol=clean, exchange="IBIS", currency="TRY")

    def get_us_contract(self, symbol: str) -> Stock:
        """
        ABD borsası için kontrat oluşturur.
        Format: STOCK, exchange="SMART", currency="USD"

        Args:
            symbol: Hisse senedi sembolü (örn: "AAPL")
        """
        return Stock(symbol=symbol, exchange="SMART", currency="USD")

    def get_eu_contract(self, symbol: str, exchange: str = "SMART") -> Stock:
        """
        Avrupa ETF'leri için SMART routing kontratı oluşturur.
        exchange parametresi artık kullanılmaz — IBKR SMART routing en uygun
        borsa/likiditeyi otomatik seçer ve Error 10311'i önler.

        Args:
            symbol: yfinance suffix'li veya temiz sembol (örn: "EXW1.DE", "VEUR.AS")
            exchange: Geriye dönük uyumluluk için korundu, dikkate alınmaz.

        Örnekler:
            get_eu_contract("EXW1.DE")  → EXW1 @ SMART, EUR
            get_eu_contract("VEUR.AS")  → VEUR @ SMART, EUR
            get_eu_contract("EUNL.DE")  → EUNL @ SMART, EUR
        """
        # yfinance suffix'ini strip et: "EXW1.DE" → "EXW1", "VEUR.AS" → "VEUR"
        clean = symbol.split(".")[0]
        return Stock(symbol=clean, exchange="SMART", currency="EUR")

    def symbol_exists_ibkr(self, symbol: str) -> bool:
        """
        IBKR'de sembolün var olup olmadığını reqMatchingSymbols ile kontrol eder.
        Bağlantı yoksa veya hata oluşursa False döner.

        Args:
            symbol: Kontrol edilecek sembol

        Returns:
            bool: Sembol IBKR'de bulunduysa True
        """
        if not self.connected:
            return False
        try:
            matches = self.ib.reqMatchingSymbols(symbol)
            return any(cd.contract.symbol == symbol for cd in matches)
        except Exception as e:
            logger.warning(f"reqMatchingSymbols hatası [{symbol}]: {e}")
            return False

    def get_forex_contract(self, base: str, quote: str) -> Forex:
        """
        IBKR Forex kontratı oluşturur.
        Forex(pair) formatı: 6 karakterlik string, secType='CASH', exchange='IDEALPRO' otomatik atanır.

        Args:
            base: Baz para birimi (örn: "EUR")
            quote: Karşı para birimi (örn: "USD")

        Örnekler:
            get_forex_contract("EUR", "USD")  → EUR.USD @ IDEALPRO
            get_forex_contract("EUR", "RON")  → EUR.RON @ IDEALPRO
            get_forex_contract("USD", "TRY")  → USD.TRY @ IDEALPRO
        """
        return Forex(f"{base}{quote}")

    def qualify_contract(self, contract: Contract) -> Contract:
        """
        IBKR'den kontrat detaylarını çeker ve doğrular.

        Args:
            contract: Doğrulanacak kontrat

        Returns:
            Doğrulanmış kontrat
        """
        try:
            qualified = self.ib.qualifyContracts(contract)
            if qualified:
                return qualified[0]
            else:
                raise ValueError(f"Kontrat doğrulanamadı: {contract.symbol}")
        except Exception as e:
            logger.error(f"Kontrat doğrulama hatası [{contract.symbol}]: {e}")
            raise

    def get_portfolio(self) -> list:
        """
        Mevcut portföy pozisyonlarını döndürür.

        Returns:
            list: Açık pozisyon listesi
        """
        try:
            return self.ib.portfolio()
        except Exception as e:
            logger.error(f"Portföy bilgisi alınamadı: {e}")
            return []
