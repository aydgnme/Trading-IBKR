# Trading Bot

Bu proje, Interactive Brokers (IBKR) ile emir iletebilen, birden fazla teknik stratejiyi aynı anda çalıştırabilen ve sonuçları yerel olarak saklayabilen Python tabanlı bir algoritmik alım-satım botudur. Kod tabanı; sinyal üretimi, risk yönetimi, emir yönetimi, Telegram bildirimi, Streamlit dashboard, Flask webhook ve backtest bileşenlerini tek bir yapı altında toplar.

## Projenin amacı

Bu botun ana amacı, belirli piyasalarda otomatik veya yarı otomatik işlem akışı kurmaktır:

- Geçmiş piyasa verisini alır.
- Stratejileri çalıştırır.
- Sinyalleri uzlaştırır.
- Risk kurallarına göre pozisyon boyutu hesaplar.
- IBKR üzerinden emir iletir veya paper trading modunda simüle eder.
- İşlem geçmişini ve günlük özeti SQLite üzerinde saklar.

## Öne çıkan özellikler

- IBKR TWS / IB Gateway bağlantısı
- Paper trading ve canlı işlem modu desteği
- Çoklu strateji mimarisi
- Risk yönetimi ve pozisyon sınırları
- SQLite tabanlı işlem ve sinyal kayıtları
- Telegram bildirimleri
- Streamlit dashboard
- TradingView webhook entegrasyonu
- Backtrader ile backtest desteği

## Kullanılan teknolojiler

- Python 3.13
- `ib_insync`
- `pandas`, `numpy`, `pandas-ta`
- `yfinance`
- `sqlalchemy` ve `sqlite3`
- `streamlit`
- `flask`
- `backtrader`
- `plotly`

## Mimari özet

Projede ana akış `main.py` üzerinden ilerler:

1. Piyasanın açık olup olmadığı kontrol edilir.
2. Her aktif sembol için geçmiş veri çekilir.
3. Stratejiler sinyal üretir.
4. Sinyaller tek bir işlem kararına dönüştürülür.
5. Risk yöneticisi işlemi onaylar veya reddeder.
6. Emir yöneticisi IBKR tarafına emir gönderir.
7. Sonuçlar veritabanına ve log dosyasına yazılır.

Bu süreç dışında iki yardımcı servis daha vardır:

- `dashboard/app.py`: işlemleri ve performansı görselleştiren arayüz
- `webhook/server.py`: TradingView veya benzeri sistemlerden gelen sinyalleri alan servis

## Varsayılan çalışma davranışı

- Varsayılan işlem modu: `IS_PAPER_TRADING=True`
- Ana log dosyası: `trading_bot.log`
- Veritabanı dosyası: `data/trading.db`
- Varsayılan aktif semboller: ABD hisseleri ve Avrupa ETF listesi
- BVB, BIST ve Forex desteği kod içinde bulunur; ancak bazı listeler ayarlarda varsayılan olarak kapalıdır

Aktif ABD sembolleri:

- `AAPL`
- `MSFT`
- `TSLA`
- `NVDA`
- `SPY`
- `AMZN`
- `GOOGL`
- `META`

Aktif Avrupa ETF sembolleri:

- `EXW1.DE`
- `EXS1.DE`
- `VEUR.AS`
- `IWDA.AS`
- `EUNL.DE`
- `SXR8.DE`
- `EXSA.DE`

## Kullanılan stratejiler

Projede şu an üç temel strateji yer alıyor:

- `RSI_MACD`: RSI ve MACD kesişimine göre sinyal üretir
- `Bollinger_RSI`: Bollinger bantları ve RSI ile mean-reversion yaklaşımı uygular
- `EMA_Trend`: EMA20, EMA50 ve EMA200 ile trend yönü ve pullback noktası arar

Ana döngü, bu stratejilerden gelen sinyalleri birlikte değerlendirir. Aynı yönde birden fazla onay gelirse sinyal daha güçlü kabul edilir.

## Dizin yapısı

```text
trading-bot/
├── backtest/          # Backtrader tabanlı backtest bileşenleri
├── broker/            # IBKR istemcisi ve emir yönetimi
├── config/            # Genel ayarlar ve risk parametreleri
├── dashboard/         # Streamlit dashboard
├── data/              # Veri çekme ve SQLite veritabanı
├── notifications/     # Telegram bildirimleri
├── risk/              # Risk yönetimi
├── strategies/        # İşlem stratejileri
├── tests/             # Sistem test scripti
├── webhook/           # Flask webhook sunucusu
├── main.py            # Ana bot döngüsü
└── requirements.txt   # Python bağımlılıkları
```

## Kurulum

### 1. Sanal ortam oluştur

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Bağımlılıkları yükle

```bash
pip install -r requirements.txt
```

### 3. Ortam dosyasını hazırla

```bash
cp .env.example .env
```

### 4. Gerekli ayarları doldur

`.env` içinde en az şu alanları kontrol et:

- `IBKR_HOST`
- `IBKR_CLIENT_ID`
- `IS_PAPER_TRADING`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `WEBHOOK_SECRET`

## Ortam değişkenleri

| Değişken | Açıklama | Varsayılan |
| --- | --- | --- |
| `IBKR_HOST` | IBKR TWS / Gateway adresi | `127.0.0.1` |
| `IBKR_PORT` | `.env.example` içinde bulunur | `7497` |
| `IBKR_CLIENT_ID` | IBKR istemci kimliği | `1` |
| `IS_PAPER_TRADING` | Simülasyon modunu açar/kapatır | `True` |
| `TELEGRAM_TOKEN` | Telegram bot token değeri | boş |
| `TELEGRAM_CHAT_ID` | Telegram sohbet kimliği | boş |
| `WEBHOOK_SECRET` | Webhook güvenlik anahtarı | boş |
| `WEBHOOK_PORT` | Flask webhook portu | `5000` |
| `LOG_LEVEL` | Log seviyesi | `INFO` |

Not: Mevcut `broker/ibkr_client.py` kodu, portu doğrudan `IS_PAPER_TRADING` durumuna göre seçiyor. Yani pratikte paper mod için `7497`, canlı mod için `7496` kullanılıyor.

## Çalıştırma

### Ana botu başlatma

```bash
python main.py
```

### Dashboard çalıştırma

```bash
streamlit run dashboard/app.py
```

### Webhook servisini başlatma

```bash
python webhook/server.py
```

### Sistem testini çalıştırma

```bash
python tests/test_system.py
```

## Webhook kullanımı

Webhook servisi, `X-Webhook-Secret` başlığı ile korunur. Örnek istek:

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your_secret_token_here" \
  -d '{
    "symbol": "AAPL",
    "action": "BUY",
    "price": 210.50,
    "timeframe": "1h",
    "strategy": "TradingView"
  }'
```

## Dashboard içinde neler var

`dashboard/app.py` içinde dört ana görünüm bulunur:

- Genel bakış
- İşlem geçmişi
- Strateji performansı
- Bot kontrol ekranı

Dashboard, verileri doğrudan `data/trading.db` ve `trading_bot.log` üzerinden okur.

## Veritabanı yapısı

SQLite veritabanında üç temel tablo oluşturulur:

- `trades`: açılan ve kapanan işlemler
- `signals`: strateji bazlı sinyaller
- `daily_summary`: günlük performans özeti

## Testler hakkında not

`tests/test_system.py`, klasik birim test paketinden çok uçtan uca kontrol scripti gibi çalışır. Bazı testler şu dış bağımlılıklara ihtiyaç duyar:

- çalışan IBKR TWS veya IB Gateway
- internet bağlantısı
- yfinance erişimi
- isteğe bağlı olarak Telegram ayarları

Bu yüzden testlerin tamamı her ortamda sorunsuz geçmeyebilir.

## Hata bildirimi

Bu projede bir hata, beklenmeyen davranış veya iyileştirme ihtiyacı görürseniz aşağıdaki kanallardan biri üzerinden bildirim yapabilirsiniz:

- E-posta: `mert@aydgn.me`
- Ticket kaydı: kullandığınız proje yönetim sistemi üzerinden yeni bir hata kaydı açabilirsiniz

Bildirim yaparken mümkünse şu bilgileri ekleyin:

- hatanın kısa açıklaması
- hatanın hangi adımda oluştuğu
- ilgili log çıktısı
- varsa ekran görüntüsü veya örnek veri
- tekrar üretme adımları

## Dikkat edilmesi gerekenler

- Bu proje doğrudan finansal işlem mantığı içerir; gerçek hesapta kullanmadan önce paper trading ile doğrulama yapılmalıdır.
- Loglar ve veritabanı dosyası yerel ortamda tutulur.
- Strateji parametreleri ve piyasa listeleri `config/` altında değiştirilebilir.
- TradingView ile entegrasyon için `webhook/server.py` ve `strategies/ema_trend.pine` birlikte değerlendirilebilir.

## Geliştirme notları

Kod tabanı modüler tutulmuş. Yeni bir strateji, yeni bir broker adaptörü veya ek raporlama ekranı eklemek görece kolaydır. En doğal genişleme noktaları şunlardır:

- `strategies/` altında yeni strateji sınıfları
- `risk/manager.py` içinde ek risk kuralları
- `dashboard/app.py` içinde yeni raporlar
- `webhook/server.py` içinde yeni sinyal kaynakları
