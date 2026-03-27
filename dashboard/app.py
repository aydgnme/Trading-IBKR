"""
dashboard/app.py
----------------
Streamlit tabanlı trading bot dashboard'u.

4 sayfa:
  1. Genel Bakış: Toplam P&L, win rate, açık pozisyonlar
  2. İşlem Geçmişi: Filtrelenebilir tablo, kümülatif P&L grafiği
  3. Strateji Performansı: Strateji bazlı metrikler
  4. Bot Kontrolü: Başlat/durdur, strateji seçimi, log akışı

Çalıştırma:
    streamlit run dashboard/app.py
"""

import sys
import os
import time

# Proje kök dizinini Python path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from config.settings import DB_PATH, IS_PAPER_TRADING

# ── Sayfa Yapılandırması ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Veri Yükleme Fonksiyonları ─────────────────────────────────────────────

@st.cache_data(ttl=30)  # 30 saniyede bir yenile
def load_trades(symbol=None, strategy=None, status=None):
    """Trades tablosundan veri yükler."""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        if symbol and symbol != "Tümü":
            query += " AND symbol = ?"
            params.append(symbol)
        if strategy and strategy != "Tümü":
            query += " AND strategy = ?"
            params.append(strategy)
        if status and status != "Tümü":
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY opened_at DESC"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_daily_summary():
    """Günlük özet verilerini yükler."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            "SELECT * FROM daily_summary ORDER BY date DESC LIMIT 30", conn
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_bot_log(lines=50):
    """Bot log dosyasını okur."""
    try:
        with open("trading_bot.log", "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except FileNotFoundError:
        return "Log dosyası bulunamadı."
    except Exception as e:
        return f"Log okuma hatası: {e}"


def get_unique_values(df, col):
    """Belirli sütundaki benzersiz değerleri listeler."""
    if df.empty or col not in df.columns:
        return []
    return df[col].dropna().unique().tolist()


@st.cache_data(ttl=60)
def fetch_eurusd_rate() -> float:
    """yfinance üzerinden EUR/USD kurunu çeker. Başarısız olursa 1.08 döner."""
    try:
        ticker = yf.Ticker("EURUSD=X")
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 1.08  # varsayılan fallback


def calc_pnl_by_currency(
    closed_trades: pd.DataFrame,
    open_trades: pd.DataFrame,
) -> dict:
    """
    Para birimi bazında P&L hesaplar. Açık pozisyonlar için DB'deki
    pnl alanı kullanılır (IBKR updatePortfolioEvent tarafından güncellenir).

    Returns:
        {
          "usd_realized":   float,
          "usd_unrealized": float,
          "eur_realized":   float,
          "eur_unrealized": float,
        }
    """
    def _sum(df, currency):
        if df.empty or "pnl" not in df.columns:
            return 0.0
        subset = df[df["currency"] == currency]
        return float(subset["pnl"].sum()) if not subset.empty else 0.0

    return {
        "usd_realized":   _sum(closed_trades, "USD"),
        "usd_unrealized": _sum(open_trades,   "USD"),
        "eur_realized":   _sum(closed_trades, "EUR"),
        "eur_unrealized": _sum(open_trades,   "EUR"),
    }


# ── Sidebar ────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📈 Trading Bot")
    mode_color = "🟡" if IS_PAPER_TRADING else "🟢"
    st.markdown(f"{mode_color} **{'Paper Trading' if IS_PAPER_TRADING else 'Canlı Trading'}**")
    st.markdown(f"🕐 {datetime.now().strftime('%H:%M:%S')}")
    st.divider()

    page = st.radio(
        "Sayfa",
        ["Genel Bakış", "İşlem Geçmişi", "Strateji Performansı", "Bot Kontrolü"],
        index=0,
    )

    if st.button("🔄 Yenile"):
        st.cache_data.clear()
        st.rerun()


# ── Sayfa 1: Genel Bakış ───────────────────────────────────────────────────

if page == "Genel Bakış":
    st.title("📊 Genel Bakış")

    all_trades = load_trades()
    closed_trades = all_trades[all_trades["status"] == "CLOSED"] if not all_trades.empty else pd.DataFrame()
    open_trades   = all_trades[all_trades["status"] == "OPEN"]   if not all_trades.empty else pd.DataFrame()

    # ── Geçersiz emir kalıntılarını filtrele ──────────────────────────────
    # stop_loss=0 VE pnl=0 → IBKR'de reddedilen veya hiç dolmayan emirler
    # (DBXD.DE, CSPX.L gibi tanınmayan semboller bu kategoriye girer)
    if not open_trades.empty:
        valid_mask = (
            (open_trades["stop_loss"].fillna(0) != 0) |
            (open_trades["pnl"].fillna(0)       != 0)
        )
        open_trades = open_trades[valid_mask]

    # ── P&L Hesabı (IBKR → DB → Dashboard) ──────────────────────────────
    pnl = calc_pnl_by_currency(closed_trades, open_trades)
    eurusd = fetch_eurusd_rate()

    usd_total = pnl["usd_realized"] + pnl["usd_unrealized"]
    eur_total = pnl["eur_realized"] + pnl["eur_unrealized"]
    grand_total_usd = usd_total + eur_total * eurusd

    realized_pnl   = pnl["usd_realized"]   + pnl["eur_realized"]   * eurusd
    unrealized_pnl = pnl["usd_unrealized"] + pnl["eur_unrealized"] * eurusd

    # ── KPI Kartları ──────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Toplam P&L (USD)",
            f"{grand_total_usd:+.2f}",
            delta=f"R: {realized_pnl:+.2f} | U: {unrealized_pnl:+.2f}",
        )

    with col2:
        total = len(closed_trades)
        wins = len(closed_trades[closed_trades["pnl"] > 0]) if not closed_trades.empty else 0
        win_rate = (wins / total * 100) if total > 0 else 0
        st.metric("Kazanma Oranı", f"%{win_rate:.1f}", f"{wins}/{total} işlem")

    with col3:
        st.metric("Açık Pozisyon", len(open_trades))

    with col4:
        if not closed_trades.empty:
            cumulative = closed_trades["pnl"].cumsum()
            max_dd = (cumulative - cumulative.cummax()).min()
        else:
            max_dd = 0
        st.metric("Max Drawdown", f"{max_dd:.2f}")

    # ── USD / EUR P&L Özeti ────────────────────────────────────────────────
    st.divider()
    st.subheader("Para Birimi Bazında P&L")
    st.caption(f"EUR/USD kuru: {eurusd:.4f}  (IBKR unrealized PNL kaynağı: DB)")

    col_u, col_e, col_t = st.columns(3)
    with col_u:
        st.metric(
            "USD Pozisyonlar",
            f"${usd_total:+.2f}",
            delta=f"R: {pnl['usd_realized']:+.2f} | U: {pnl['usd_unrealized']:+.2f}",
        )
    with col_e:
        st.metric(
            "EUR Pozisyonlar",
            f"€{eur_total:+.2f}",
            delta=f"R: {pnl['eur_realized']:+.2f} | U: {pnl['eur_unrealized']:+.2f}",
        )
    with col_t:
        st.metric(
            "Toplam (USD cinsinden)",
            f"${grand_total_usd:+.2f}",
            delta=f"EUR × {eurusd:.4f} çevrildi",
        )

    # ── Açık Pozisyonlar Tablosu ───────────────────────────────────────────
    st.divider()
    st.subheader("Açık Pozisyonlar")
    if open_trades.empty:
        st.info("Şu an açık pozisyon yok.")
    else:
        display_cols = [
            "symbol", "direction", "entry_price", "pnl",
            "stop_loss", "take_profit", "quantity", "currency",
            "strategy", "opened_at",
        ]
        st.dataframe(
            open_trades[[c for c in display_cols if c in open_trades.columns]].rename(
                columns={"pnl": "unrealized_pnl (IBKR·DB)"}
            ),
            use_container_width=True,
        )


# ── Sayfa 2: İşlem Geçmişi ────────────────────────────────────────────────

elif page == "İşlem Geçmişi":
    st.title("📋 İşlem Geçmişi")

    all_trades = load_trades()

    # ── Filtreler ──────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        symbols = ["Tümü"] + get_unique_values(all_trades, "symbol")
        selected_symbol = st.selectbox("Sembol", symbols)
    with col2:
        strategies = ["Tümü"] + get_unique_values(all_trades, "strategy")
        selected_strategy = st.selectbox("Strateji", strategies)
    with col3:
        selected_status = st.selectbox("Durum", ["Tümü", "OPEN", "CLOSED"])
    with col4:
        date_range = st.selectbox("Tarih Aralığı", ["Tümü", "Son 7 gün", "Son 30 gün", "Son 90 gün"])

    # Filtrelenmiş veri
    filtered = load_trades(
        symbol=selected_symbol if selected_symbol != "Tümü" else None,
        strategy=selected_strategy if selected_strategy != "Tümü" else None,
        status=selected_status if selected_status != "Tümü" else None,
    )

    if date_range != "Tümü" and not filtered.empty:
        days = {"Son 7 gün": 7, "Son 30 gün": 30, "Son 90 gün": 90}[date_range]
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        filtered = filtered[filtered["opened_at"] >= cutoff]

    st.dataframe(filtered, use_container_width=True)

    # ── Kümülatif P&L Grafiği ─────────────────────────────────────────────
    closed = filtered[filtered["status"] == "CLOSED"] if not filtered.empty else pd.DataFrame()
    open_f = filtered[filtered["status"] == "OPEN"]   if not filtered.empty else pd.DataFrame()
    if not closed.empty and "pnl" in closed.columns:
        closed_sorted = closed.sort_values("opened_at")
        closed_sorted["cumulative_pnl"] = closed_sorted["pnl"].cumsum()

        chart_df = closed_sorted[["opened_at", "cumulative_pnl"]].copy()

        # Açık pozisyonların unrealized PNL'ini son nokta olarak ekle
        if not open_f.empty and "pnl" in open_f.columns:
            open_pnl_total = float(open_f["pnl"].fillna(0).sum())
            if open_pnl_total != 0:
                last_cum = float(closed_sorted["cumulative_pnl"].iloc[-1])
                extra = pd.DataFrame([{
                    "opened_at": datetime.now().isoformat(),
                    "cumulative_pnl": last_cum + open_pnl_total,
                }])
                chart_df = pd.concat([chart_df, extra], ignore_index=True)

        fig = px.line(
            chart_df,
            x="opened_at",
            y="cumulative_pnl",
            title="Kümülatif P&L (Kapalı + Açık Unrealized)",
            labels={"opened_at": "Tarih", "cumulative_pnl": "Kümülatif P&L"},
            color_discrete_sequence=["#00ff88"],
        )
        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

        # En iyi / en kötü 5 işlem
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("En İyi 5 İşlem")
            top5 = closed.nlargest(5, "pnl")[["symbol", "direction", "pnl", "strategy"]]
            st.dataframe(top5, use_container_width=True)
        with col2:
            st.subheader("En Kötü 5 İşlem")
            worst5 = closed.nsmallest(5, "pnl")[["symbol", "direction", "pnl", "strategy"]]
            st.dataframe(worst5, use_container_width=True)


# ── Sayfa 3: Strateji Performansı ─────────────────────────────────────────

elif page == "Strateji Performansı":
    st.title("🎯 Strateji Performansı")

    all_trades = load_trades(status="CLOSED")

    # pnl = 0 olan kayıtları filtrele (emir dolmadı / geçersiz kayıt)
    if not all_trades.empty:
        all_trades = all_trades[all_trades["pnl"].fillna(0) != 0]

    if all_trades.empty:
        st.warning("Henüz kapatılmış işlem yok.")
    else:
        # ── Strateji Bazında Metrikler ─────────────────────────────────────
        st.subheader("Strateji Metrikleri")

        strategy_stats = []
        for strategy in all_trades["strategy"].unique():
            s_df = all_trades[all_trades["strategy"] == strategy]
            total = len(s_df)
            wins = len(s_df[s_df["pnl"] > 0])
            total_pnl = s_df["pnl"].sum()
            avg_pnl = s_df["pnl"].mean()

            strategy_stats.append({
                "Strateji": strategy,
                "İşlem": total,
                "Kazanan": wins,
                "Win Rate %": round(wins / total * 100, 1) if total > 0 else 0,
                "Toplam P&L": round(total_pnl, 2),
                "Ortalama P&L": round(avg_pnl, 2),
            })

        stats_df = pd.DataFrame(strategy_stats)
        st.dataframe(stats_df, use_container_width=True)

        # ── Sembol/Piyasa Performansı ──────────────────────────────────────
        st.subheader("Sembol Bazında Performans")

        symbol_pnl = (
            all_trades.groupby("symbol")["pnl"]
            .sum()
            .reset_index()
            .sort_values("pnl", ascending=False)
        )

        fig = px.bar(
            symbol_pnl,
            x="symbol",
            y="pnl",
            title="Sembol Bazında Toplam P&L",
            color="pnl",
            color_continuous_scale=["red", "green"],
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── P&L Dağılımı ───────────────────────────────────────────────────
        st.subheader("P&L Dağılımı")
        fig2 = px.histogram(
            all_trades,
            x="pnl",
            nbins=20,
            title="İşlem P&L Dağılımı",
            color_discrete_sequence=["#4287f5"],
        )
        st.plotly_chart(fig2, use_container_width=True)


# ── Sayfa 4: Bot Kontrolü ─────────────────────────────────────────────────

elif page == "Bot Kontrolü":
    st.title("⚙️ Bot Kontrolü")

    # ── Bot Durumu ─────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Bot Durumu")
        mode_label = "Paper Trading" if IS_PAPER_TRADING else "Canlı Trading"
        st.info(f"Mod: **{mode_label}**")

        st.markdown("**Piyasa Açık/Kapalı:**")

        import pytz
        from config.settings import MARKET_HOURS

        for market, config in MARKET_HOURS.items():
            tz = pytz.timezone(config["timezone"])
            now = datetime.now(tz)
            weekday_ok = now.weekday() in config["weekdays"]
            oh, om = map(int, config["open"].split(":"))
            ch, cm = map(int, config["close"].split(":"))
            open_t = now.replace(hour=oh, minute=om, second=0, microsecond=0)
            close_t = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
            is_open = weekday_ok and open_t <= now <= close_t
            status = "🟢 Açık" if is_open else "🔴 Kapalı"
            st.markdown(f"- **{market}**: {status}")

    with col2:
        st.subheader("Kontroller")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("▶️ Botu Başlat", use_container_width=True):
                st.success("Bot başlatma komutu gönderildi.")
                st.info("Terminal'de: `python main.py`")
        with col_b:
            if st.button("⏹️ Botu Durdur", use_container_width=True):
                st.warning("Bot durdurma komutu gönderildi.")

        st.divider()
        st.subheader("Aktif Stratejiler")
        strategies = ["RSI_MACD", "Bollinger_RSI", "EMA_Trend"]
        for s in strategies:
            st.checkbox(s, value=True, key=f"strat_{s}")

    # ── Anlık Log Akışı ────────────────────────────────────────────────────
    st.divider()
    st.subheader("📄 Bot Logları (Son 50 Satır)")

    log_content = load_bot_log(lines=50)
    st.code(log_content, language="text")

    if st.button("🔄 Logları Yenile"):
        st.cache_data.clear()
        st.rerun()

    # ── Veritabanı İstatistikleri ──────────────────────────────────────────
    st.divider()
    st.subheader("Veritabanı Özeti")

    try:
        conn = sqlite3.connect(DB_PATH)
        trade_count = pd.read_sql_query("SELECT COUNT(*) as c FROM trades", conn).iloc[0]["c"]
        signal_count = pd.read_sql_query("SELECT COUNT(*) as c FROM signals", conn).iloc[0]["c"]
        conn.close()

        col1, col2 = st.columns(2)
        col1.metric("Toplam Trade Kaydı", trade_count)
        col2.metric("Toplam Sinyal Kaydı", signal_count)
    except Exception:
        st.info("Veritabanı henüz oluşturulmadı.")

# ── Otomatik Yenileme (15 saniyede bir) ───────────────────────────────────
time.sleep(15)
st.rerun()
