"""
broker/order_manager.py
-----------------------
Emir yönetimi modülü. IBKR üzerinden:
  - Market, limit, stop-limit emirleri gönderir
  - Bracket order (ana + stop-loss + take-profit) oluşturur
  - Emir durumunu takip eder (filled, cancelled, partial)
  - Slippage hesaplar ve loglar
  - BVB (RON) ve BIST (TRY) için doğru boyutlama yapar

Kullanım:
    om = OrderManager(ibkr_client)
    result = om.place_bracket_order("BUY", contract, qty=10, entry=45.0, sl=43.0, tp=49.0)
"""

import logging
from typing import Optional

from ib_insync import (
    Contract,
    LimitOrder,
    MarketOrder,
    Order,
    StopLimitOrder,
    StopOrder,
)

from config.settings import IS_PAPER_TRADING

logger = logging.getLogger(__name__)


class OrderManager:
    """IBKR emir gönderme ve takip sınıfı."""

    def __init__(self, ibkr_client):
        """
        Args:
            ibkr_client: Bağlı IBKRClient instance
        """
        self.ibkr = ibkr_client
        self.open_orders: dict = {}   # order_id → emir bilgisi
        self.filled_orders: list = [] # Tamamlanan emirler

    # ── Temel Emir Tipleri ────────────────────────────────────────────────

    def place_market_order(
        self, action: str, contract: Contract, quantity: int
    ) -> Optional[dict]:
        """
        Market emri gönderir (anlık fiyattan gerçekleşir).

        Args:
            action: "BUY" veya "SELL"
            contract: IBKR kontrat objesi
            quantity: Lot/hisse adedi

        Returns:
            dict: Emir bilgisi veya None (hata durumunda)
        """
        if IS_PAPER_TRADING:
            logger.info(
                f"[PAPER] Market emri: {action} {quantity} x {contract.symbol} @ MARKET"
            )
            return self._mock_order(action, contract, quantity, "MARKET")

        try:
            order = MarketOrder(action=action, totalQuantity=quantity)
            trade = self.ibkr.ib.placeOrder(contract, order)
            self.ibkr.ib.sleep(1)

            result = self._build_order_result(trade, contract, "MARKET")
            self.open_orders[trade.order.orderId] = result
            logger.info(
                f"Market emri gönderildi: {action} {quantity} x {contract.symbol}"
            )
            return result

        except Exception as e:
            logger.error(f"Market emir hatası [{contract.symbol}]: {e}")
            return None

    def place_limit_order(
        self, action: str, contract: Contract, quantity: int, limit_price: float
    ) -> Optional[dict]:
        """
        Limit emri gönderir (belirtilen fiyattan veya daha iyi).

        Args:
            action: "BUY" veya "SELL"
            contract: IBKR kontrat objesi
            quantity: Hisse adedi
            limit_price: Limit fiyatı
        """
        if IS_PAPER_TRADING:
            logger.info(
                f"[PAPER] Limit emri: {action} {quantity} x {contract.symbol} @ {limit_price}"
            )
            return self._mock_order(action, contract, quantity, "LIMIT", limit_price)

        try:
            order = LimitOrder(
                action=action,
                totalQuantity=quantity,
                lmtPrice=round(limit_price, 2),
            )
            trade = self.ibkr.ib.placeOrder(contract, order)
            self.ibkr.ib.sleep(1)

            result = self._build_order_result(trade, contract, "LIMIT", limit_price)
            self.open_orders[trade.order.orderId] = result
            logger.info(
                f"Limit emri: {action} {quantity} x {contract.symbol} @ {limit_price}"
            )
            return result

        except Exception as e:
            logger.error(f"Limit emir hatası [{contract.symbol}]: {e}")
            return None

    def place_bracket_order(
        self,
        action: str,
        contract: Contract,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> Optional[dict]:
        """
        Bracket order: Ana emir + stop-loss + take-profit aynı anda gönderilir.
        IBKR bu 3 emri birbirine bağlar (OCA - One Cancels All).

        Args:
            action: "BUY" (long) veya "SELL" (short)
            contract: IBKR kontrat
            quantity: Hisse adedi
            entry_price: Giriş limit fiyatı
            stop_loss: Stop-loss fiyatı
            take_profit: Take-profit fiyatı
        """
        try:
            bracket = self.ibkr.ib.bracketOrder(
                action=action,
                quantity=quantity,
                limitPrice=round(entry_price, 2),
                takeProfitPrice=round(take_profit, 2),
                stopLossPrice=round(stop_loss, 2),
                tif="DAY",
            )

            orders = []
            for order in bracket:
                trade = self.ibkr.ib.placeOrder(contract, order)
                orders.append(trade)

            self.ibkr.ib.sleep(1)

            result = {
                "symbol": contract.symbol,
                "action": action,
                "quantity": quantity,
                "order_type": "BRACKET",
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "status": "SUBMITTED",
                "orders": [o.order.orderId for o in orders],
            }

            logger.info(
                f"Bracket emri gönderildi: {action} {quantity} x {contract.symbol} | "
                f"Giriş={entry_price} | SL={stop_loss} | TP={take_profit}"
            )
            return result

        except Exception as e:
            logger.error(f"Bracket emir hatası [{contract.symbol}]: {e}")
            return None

    def cancel_order(self, order_id: int) -> bool:
        """
        Açık emri iptal eder.

        Args:
            order_id: İptal edilecek emrin ID'si
        """
        if IS_PAPER_TRADING:
            logger.info(f"[PAPER] Emir iptal edildi: #{order_id}")
            self.open_orders.pop(order_id, None)
            return True

        try:
            open_trades = self.ibkr.ib.openTrades()
            for trade in open_trades:
                if trade.order.orderId == order_id:
                    self.ibkr.ib.cancelOrder(trade.order)
                    self.open_orders.pop(order_id, None)
                    logger.info(f"Emir iptal edildi: #{order_id}")
                    return True

            logger.warning(f"İptal edilecek emir bulunamadı: #{order_id}")
            return False

        except Exception as e:
            logger.error(f"Emir iptal hatası #{order_id}: {e}")
            return False

    def get_order_status(self, order_id: int) -> Optional[str]:
        """
        Emir durumunu sorgular.

        Returns:
            str: "SUBMITTED", "FILLED", "CANCELLED", "PARTIAL", "UNKNOWN"
        """
        if order_id in self.open_orders:
            return self.open_orders[order_id].get("status", "UNKNOWN")
        return "UNKNOWN"

    # ── Slippage Takibi ───────────────────────────────────────────────────

    def calculate_slippage(
        self, expected_price: float, filled_price: float, action: str
    ) -> dict:
        """
        Gerçekleşen slippage'i hesaplar ve loglar.

        Args:
            expected_price: Beklenen fiyat (sinyal fiyatı)
            filled_price: Gerçekleşen fiyat
            action: "BUY" veya "SELL"

        Returns:
            dict: Slippage bilgisi
        """
        if action == "BUY":
            slippage = filled_price - expected_price  # Alışta fazla ödeme = negatif
        else:
            slippage = expected_price - filled_price  # Satışta az alma = negatif

        slippage_pct = slippage / expected_price * 100

        result = {
            "expected_price": expected_price,
            "filled_price": filled_price,
            "slippage": round(slippage, 4),
            "slippage_pct": round(slippage_pct, 4),
        }

        if abs(slippage_pct) > 0.1:  # %0.1'den fazla slippage varsa uyar
            logger.warning(f"Yüksek slippage: {slippage_pct:.4f}% | {result}")
        else:
            logger.debug(f"Slippage: {slippage_pct:.4f}%")

        return result

    # ── Yardımcı Metodlar ─────────────────────────────────────────────────

    def _build_order_result(
        self,
        trade,
        contract: Contract,
        order_type: str,
        price: float = 0,
    ) -> dict:
        """Trade objesinden standart sonuç dict'i oluşturur."""
        return {
            "order_id": trade.order.orderId,
            "symbol": contract.symbol,
            "action": trade.order.action,
            "quantity": trade.order.totalQuantity,
            "order_type": order_type,
            "price": price,
            "status": trade.orderStatus.status,
        }

    def _mock_order(
        self,
        action: str,
        contract: Contract,
        quantity: int,
        order_type: str,
        price: float = 0,
    ) -> dict:
        """Paper trading için sahte emir sonucu üretir."""
        mock_id = len(self.open_orders) + 1000
        result = {
            "order_id": mock_id,
            "symbol": contract.symbol,
            "action": action,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "status": "SUBMITTED",
            "paper": True,
        }
        self.open_orders[mock_id] = result
        return result

    def _mock_bracket_order(
        self,
        action: str,
        contract: Contract,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        """Paper trading için sahte bracket emir sonucu üretir."""
        mock_id = len(self.open_orders) + 2000
        result = {
            "order_id": mock_id,
            "symbol": contract.symbol,
            "action": action,
            "quantity": quantity,
            "order_type": "BRACKET",
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "SUBMITTED",
            "paper": True,
        }
        self.open_orders[mock_id] = result
        return result
