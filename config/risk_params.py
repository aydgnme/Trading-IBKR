"""
config/risk_params.py
---------------------
Risk yönetimi parametreleri. Bu değerleri değiştirerek botun
risk davranışını kontrol edebilirsiniz.
"""

# ── Pozisyon Risk Kuralları ────────────────────────────────────────────────
MAX_RISK_PER_TRADE = 0.02       # İşlem başına maksimum sermaye riski: %2
MAX_OPEN_POSITIONS = 32          # Aynı anda maksimum açık pozisyon sayısı
DAILY_LOSS_LIMIT = 0.05         # Günlük maksimum kayıp: sermayenin %5'i

# ── Stop-Loss / Take-Profit ────────────────────────────────────────────────
ATR_PERIOD = 14                 # ATR hesaplama periyodu
ATR_MULTIPLIER = 1.5            # Stop-loss = ATR × bu çarpan
MIN_RISK_REWARD = 2.0           # Minimum risk/ödül oranı (1:2)

# ── Korelasyon Kontrolü ────────────────────────────────────────────────────
MAX_SAME_SECTOR_POSITIONS = 2   # Aynı sektörde maksimum pozisyon sayısı

# ── Forex Pozisyon Sınırı ──────────────────────────────────────────────────
FOREX_MAX_UNITS = 10_000        # Forex iznini aşmamak için maksimum lot birimi

# ── Komisyon Ayarları ──────────────────────────────────────────────────────
COMMISSION_RATE = 0.001         # %0.1 komisyon

# ── Slippage Tahmini ───────────────────────────────────────────────────────
SLIPPAGE_ESTIMATE = 0.0005      # %0.05 slippage tahmini

# ── Sektör Eşleştirmesi ────────────────────────────────────────────────────
SECTOR_MAP = {
    # BVB
    "TLV.RO": "banking",
    "BRD.RO": "banking",
    "SNP.RO": "energy",
    "TGN.RO": "energy",
    "SNG.RO": "energy",
    # BIST
    "THYAO.IS": "aviation",
    "GARAN.IS": "banking",
    "ASELS.IS": "defense",
    "EREGL.IS": "steel",
    "BIMAS.IS": "retail",
}
