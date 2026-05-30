# MSB Alert Bot — Kurulum Rehberi

## 1. Telegram Bot Kur

### Bot Token Al
1. Telegram'da @BotFather'a yaz
2. `/newbot` yaz
3. Bot adı ver (örn: "MSB Alert Bot")
4. Sana bir TOKEN verecek: `7123456789:AAFxxx...`

### Chat ID Al
1. Telegram'da @userinfobot'a yaz
2. Sana `id: 123456789` formatında Chat ID verecek

## 2. .env Dosyası Oluştur

```bash
cp .env.example .env
```

`.env` dosyasını aç ve gerçek değerleri yaz:

```
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxYYYzzz
TELEGRAM_CHAT_ID=123456789
```

> ⚠️ `.env` dosyası `.gitignore`'da — GitHub'a **asla gitmez**.  
> Sadece `.env.example` commit edilir, token'lar orada boş kalır.

## 3. Kütüphaneleri Kur

```bash
pip install -r requirements.txt
```

## 4. Çalıştır

```bash
python msb_alert.py
```

## 5. Arka Planda Çalıştır (Linux/Mac)

```bash
nohup python msb_alert.py > output.log 2>&1 &
```

PID'i öğrenmek için:
```bash
ps aux | grep msb_alert
```

Durdurmak için:
```bash
kill <PID>
```

## 6. Windows'ta Arka Planda

```batch
start /B python msb_alert.py > output.log 2>&1
```

## Parametreler

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| CHECK_INTERVAL | 300 | Kaç saniyede bir kontrol (300 = 5 dk) |
| ZIGZAG_LEN | 9 | ZigZag uzunluğu (Pine ile aynı) |
| FIB_FACTOR | 0.33 | MSB onay faktörü |
| ENTRY_TOLERANCE | 0.1 | Zone girişi toleransı (ATR çarpanı) |
| LOOKBACK_MONTHS | 3 | Kaç aylık veri |

## Telegram Mesaj Örneği

```
🟢 MSB Zone Girişi — BULLISH
━━━━━━━━━━━━━━━━━━━━
📊 BTC/USDT 1h
⏰ 2026-05-30 14:35 UTC

📦 Zone Tipi: BULLISH OB-BB
📈 Zone Üst:  $68,450.00
📉 Zone Alt:  $67,200.00
📐 Zone Genişliği: $1,250.00
💰 Mevcut Fiyat: $67,800.00
📍 Zone ortasından uzaklık: %0.48

⚡ LONG fırsatı!
━━━━━━━━━━━━━━━━━━━━
```

## Log Dosyası

Bot `msb_alert.log` dosyasına logları yazar.
Geçmiş alertler `sent_alerts.json` dosyasına kaydedilir (tekrar gönderim önlenir).
