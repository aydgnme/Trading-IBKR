"""
backtest/runner.py
------------------
Backtest motoru. backtrader kütüphanesi kullanılarak:
  - Basit EMA crossover stratejisi
  - Her 3 strateji (RSI+MACD, Bollinger, EMA Trend) karşılaştırması
  - Grid search ile parametre optimizasyonu
  - Sonuçlar: Toplam getiri, Sharpe oranı, Max Drawdown, Win Rate

Kullanım:
    runner = BacktestRunner()
    results = runner.run_ema_crossover("TLV", "BVB")
    runner.compare_strategies("THYAO", "BIST")
"""

import logging
from typing import Optional

import backtrader as bt
import pandas as pd
import yfinance as yf

from config.settings import INITIAL_CAPITAL_USD
from config.risk_params import COMMISSION_RATE

logger = logging.getLogger(__name__)


# ── Backtrader Stratejileri ────────────────────────────────────────────────

class EMACrossoverBT(bt.Strategy):
    """Backtrader için EMA Crossover stratejisi."""

    params = (
        ("ema_fast", 20),
        ("ema_slow", 50),
        ("printlog", False),
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(
            self.data.close, period=self.params.ema_fast
        )
        self.ema_slow = bt.indicators.EMA(
            self.data.close, period=self.params.ema_slow
        )
        self.crossover = bt.indicators.CrossOver(self.ema_fast, self.ema_slow)

    def next(self):
        if self.crossover > 0 and not self.position:
            self.buy()
        elif self.crossover < 0 and self.position:
            self.sell()

    def log(self, txt):
        if self.params.printlog:
            dt = self.datas[0].datetime.date(0)
            logger.info(f"[EMA Crossover BT] {dt}: {txt}")


class RSIMACDBt(bt.Strategy):
    """Backtrader için RSI + MACD stratejisi."""

    params = (
        ("rsi_period", 14),
        ("macd_fast", 12),
        ("macd_slow", 26),
        ("macd_signal", 9),
        ("rsi_oversold", 30),
        ("rsi_overbought", 70),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(
            self.data.close, period=self.params.rsi_period
        )
        self.macd = bt.indicators.MACD(
            self.data.close,
            period1=self.params.macd_fast,
            period2=self.params.macd_slow,
            period_signal=self.params.macd_signal,
        )
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

    def next(self):
        if (
            self.rsi < self.params.rsi_oversold
            and self.crossover > 0
            and not self.position
        ):
            self.buy()
        elif (
            self.rsi > self.params.rsi_overbought
            and self.crossover < 0
            and self.position
        ):
            self.sell()


class BollingerBT(bt.Strategy):
    """Backtrader için Bollinger Band + RSI stratejisi."""

    params = (
        ("bb_period", 20),
        ("bb_devfactor", 2.0),
        ("rsi_period", 14),
        ("rsi_buy", 35),
        ("rsi_sell", 65),
    )

    def __init__(self):
        self.boll = bt.indicators.BollingerBands(
            self.data.close,
            period=self.params.bb_period,
            devfactor=self.params.bb_devfactor,
        )
        self.rsi = bt.indicators.RSI(
            self.data.close, period=self.params.rsi_period
        )

    def next(self):
        price = self.data.close[0]
        if price <= self.boll.lines.bot[0] and self.rsi < self.params.rsi_buy:
            if not self.position:
                self.buy()
        elif price >= self.boll.lines.top[0] and self.rsi > self.params.rsi_sell:
            if self.position:
                self.sell()


# ── Yardımcı Analiz ────────────────────────────────────────────────────────

class TradeAnalyzer(bt.Analyzer):
    """İşlem istatistiklerini toplayan özel analyzer."""

    def create_analysis(self):
        self.rets = {}

    def stop(self):
        analysis = self.strategy.analyzers.tradeanalyzer.get_analysis()

        total = analysis.get("total", {})
        won = analysis.get("won", {})
        lost = analysis.get("lost", {})

        total_trades = total.get("total", 0)
        won_trades = won.get("total", 0)

        self.rets["total_trades"] = total_trades
        self.rets["win_rate"] = (
            round(won_trades / total_trades * 100, 2) if total_trades > 0 else 0
        )


# ── Ana Backtest Sınıfı ────────────────────────────────────────────────────

class BacktestRunner:
    """Backtest çalıştıran ve sonuçları raporlayan sınıf."""

    def __init__(
        self,
        initial_capital: float = INITIAL_CAPITAL_USD,
        commission: float = COMMISSION_RATE,
    ):
        self.initial_capital = initial_capital
        self.commission = commission

    def _load_data(self, symbol: str, market: str, period: str = "2y") -> Optional[bt.feeds.PandasData]:
        """
        yfinance'den veri çeker ve backtrader feed'ine dönüştürür.
        """
        # Sembol formatı
        if market == "BIST":
            ticker_sym = f"{symbol}.IS"
        else:
            ticker_sym = symbol

        try:
            df = yf.download(ticker_sym, period=period, progress=False)
            if df.empty:
                logger.error(f"Veri çekilemedi: {ticker_sym}")
                return None

            df.columns = [c.lower() for c in df.columns]
            df.index = pd.to_datetime(df.index)

            feed = bt.feeds.PandasData(dataname=df)
            logger.info(f"Veri yüklendi: {ticker_sym} | {len(df)} bar")
            return feed

        except Exception as e:
            logger.error(f"Veri yükleme hatası [{symbol}]: {e}")
            return None

    def _run_cerebro(self, strategy_class, data_feed, strategy_params: dict = None) -> dict:
        """
        Backtrader cerebro instance'ı oluşturur ve çalıştırır.

        Returns:
            dict: Backtest sonuçları
        """
        cerebro = bt.Cerebro()

        # Strateji ekle
        if strategy_params:
            cerebro.addstrategy(strategy_class, **strategy_params)
        else:
            cerebro.addstrategy(strategy_class)

        # Veri ekle
        cerebro.adddata(data_feed)

        # Sermaye ve komisyon ayarla
        cerebro.broker.setcash(self.initial_capital)
        cerebro.broker.setcommission(commission=self.commission)

        # Analizörler ekle
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="tradeanalyzer")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

        # Çalıştır
        start_value = cerebro.broker.getvalue()
        results = cerebro.run()
        end_value = cerebro.broker.getvalue()

        strat = results[0]

        # Sonuçları topla
        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        trade_analysis = strat.analyzers.tradeanalyzer.get_analysis()

        total_trades = trade_analysis.get("total", {}).get("total", 0)
        won_trades = trade_analysis.get("won", {}).get("total", 0)

        return {
            "start_value": round(start_value, 2),
            "end_value": round(end_value, 2),
            "total_return_pct": round((end_value - start_value) / start_value * 100, 2),
            "sharpe_ratio": round(sharpe.get("sharperatio") or 0, 4),
            "max_drawdown_pct": round(drawdown.get("max", {}).get("drawdown", 0), 2),
            "total_trades": total_trades,
            "win_rate_pct": round(won_trades / total_trades * 100, 2) if total_trades > 0 else 0,
        }

    def run_ema_crossover(
        self, symbol: str, market: str = "BVB", period: str = "2y"
    ) -> Optional[dict]:
        """
        EMA Crossover stratejisini çalıştırır.

        Args:
            symbol: Hisse sembolü
            market: Piyasa ("BVB" veya "BIST")
            period: Geçmiş veri süresi

        Returns:
            dict: Backtest sonuçları
        """
        logger.info(f"EMA Crossover backtest başlıyor: {symbol} [{market}]")

        data_feed = self._load_data(symbol, market, period)
        if data_feed is None:
            return None

        results = self._run_cerebro(EMACrossoverBT, data_feed)
        self._print_results(f"EMA Crossover | {symbol}", results)
        return results

    def compare_strategies(
        self, symbol: str, market: str = "BVB", period: str = "2y"
    ) -> dict:
        """
        Üç stratejiyi aynı veri seti üzerinde karşılaştırır.

        Returns:
            dict: Strateji → sonuçlar eşleşmesi
        """
        logger.info(f"Strateji karşılaştırması: {symbol} [{market}]")

        data_feed = self._load_data(symbol, market, period)
        if data_feed is None:
            return {}

        strategies = {
            "EMA_Crossover": (EMACrossoverBT, {}),
            "RSI_MACD": (RSIMACDBt, {}),
            "Bollinger_RSI": (BollingerBT, {}),
        }

        comparison = {}
        for name, (strategy_class, params) in strategies.items():
            # Her strateji için yeni data feed gerekli
            fresh_feed = self._load_data(symbol, market, period)
            if fresh_feed:
                result = self._run_cerebro(strategy_class, fresh_feed, params)
                comparison[name] = result

        self._print_comparison_table(symbol, comparison)
        return comparison

    def grid_search(
        self,
        symbol: str,
        market: str = "BVB",
        period: str = "2y",
        param_grid: dict = None,
    ) -> list:
        """
        Grid search ile en iyi EMA parametrelerini bulur.

        Args:
            param_grid: {"ema_fast": [10, 20], "ema_slow": [50, 100]}

        Returns:
            list: Sonuçlar (Sharpe'a göre sıralı)
        """
        if param_grid is None:
            param_grid = {
                "ema_fast": [10, 20, 30],
                "ema_slow": [50, 100, 200],
            }

        logger.info(f"Grid search başlıyor: {symbol}")
        all_results = []

        fast_list = param_grid.get("ema_fast", [20])
        slow_list = param_grid.get("ema_slow", [50])

        for fast in fast_list:
            for slow in slow_list:
                if fast >= slow:
                    continue  # Geçersiz kombinasyon

                data_feed = self._load_data(symbol, market, period)
                if data_feed is None:
                    continue

                params = {"ema_fast": fast, "ema_slow": slow}
                result = self._run_cerebro(EMACrossoverBT, data_feed, params)
                result["params"] = params
                all_results.append(result)

        # Sharpe oranına göre sırala
        all_results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

        logger.info("\n=== Grid Search Sonuçları ===")
        for i, r in enumerate(all_results[:5], 1):
            logger.info(
                f"{i}. EMA{r['params']['ema_fast']}/{r['params']['ema_slow']} | "
                f"Getiri={r['total_return_pct']}% | Sharpe={r['sharpe_ratio']}"
            )

        return all_results

    def _print_results(self, title: str, results: dict):
        """Backtest sonuçlarını konsola yazdırır."""
        print(f"\n{'='*50}")
        print(f"  {title}")
        print(f"{'='*50}")
        print(f"  Başlangıç Sermayesi : ${results['start_value']:,.2f}")
        print(f"  Bitiş Sermayesi     : ${results['end_value']:,.2f}")
        print(f"  Toplam Getiri       : %{results['total_return_pct']:.2f}")
        print(f"  Sharpe Oranı        : {results['sharpe_ratio']:.4f}")
        print(f"  Max Drawdown        : %{results['max_drawdown_pct']:.2f}")
        print(f"  Toplam İşlem        : {results['total_trades']}")
        print(f"  Kazanma Oranı       : %{results['win_rate_pct']:.2f}")
        print(f"{'='*50}\n")

    def _print_comparison_table(self, symbol: str, comparison: dict):
        """Karşılaştırma tablosunu yazdırır."""
        print(f"\n{'='*70}")
        print(f"  STRATEJİ KARŞILAŞTIRMASI: {symbol}")
        print(f"{'='*70}")
        print(
            f"  {'Strateji':<20} {'Getiri%':>8} {'Sharpe':>8} "
            f"{'MaxDD%':>8} {'WinRate%':>10} {'İşlem':>7}"
        )
        print(f"  {'-'*60}")
        for name, r in comparison.items():
            print(
                f"  {name:<20} {r['total_return_pct']:>8.2f} "
                f"{r['sharpe_ratio']:>8.4f} {r['max_drawdown_pct']:>8.2f} "
                f"{r['win_rate_pct']:>10.2f} {r['total_trades']:>7}"
            )
        print(f"{'='*70}\n")


if __name__ == "__main__":
    # Direkt çalıştırma testi
    logging.basicConfig(level=logging.INFO)
    runner = BacktestRunner()

    print("BVB - TLV EMA Crossover Backtest:")
    runner.run_ema_crossover("TLV", "BVB")

    print("\nBIST - THYAO Strateji Karşılaştırması:")
    runner.compare_strategies("THYAO", "BIST")
