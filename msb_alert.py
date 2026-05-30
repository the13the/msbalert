"""
MSB - Market Structure Break + OB/BB Kesişim Zone Detector
BTC/USDT 1h | Telegram Alert

Pine Script'ten birebir çevrilen logic:
- ZigZag ile swing high/low tespiti
- MSB (Market Structure Break) — fib_factor onaylı
- Bullish: OB (son bearish mum h1→l0 arasında) + BB/MB (l1→h1 arasında bullish mum) kesişimi
- Bearish: OB (son bullish mum l1→h0 arasında) + BB/MB (h1→l1 arasında bearish mum) kesişimi
- Aktif zone listesi tutulur
- Her döngüde fiyat zone'a girdi mi kontrol edilir
- Telegram'a detaylı mesaj gönderilir
"""

import pandas as pd
import numpy as np
import time
import logging
import json
import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# ─────────────────────────────────────────
# AYARLAR — .env dosyasından yükle
# ─────────────────────────────────────────

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise EnvironmentError(
        "TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID tanımlanmamış!\n"
        ".env dosyası oluştur veya ortam değişkenlerini tanımla.\n"
        "Bkz: README.md"
    )

SYMBOL         = "BTC-USD"
DISPLAY_SYMBOL = "BTC/USDT"
TIMEFRAME      = "1h"
CHECK_INTERVAL = 300          # saniye (5 dakikada bir kontrol)
LOOKBACK_MONTHS = 3           # kaç aylık veri

# Pine Script parametreleri
ZIGZAG_LEN  = 9
FIB_FACTOR  = 0.33

# Zone'a "girdi" sayılma toleransı (ATR çarpanı)
ENTRY_TOLERANCE = 0.1

# Daha önce alert gönderilmiş zone'ları tekrar atma (dosyaya kaydeder)
SENT_ALERTS_FILE = "sent_alerts.json"

# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("msb_alert.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────

def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info("Telegram mesajı gönderildi.")
            return True
        else:
            log.error(f"Telegram hatası: {r.status_code} | {r.text}")
            return False
    except Exception as e:
        log.error(f"Telegram bağlantı hatası: {e}")
        return False

def test_telegram():
    msg = (
        "🤖 <b>MSB Alert Bot Başladı</b>\n\n"
        f"📊 Sembol: <b>{DISPLAY_SYMBOL} {TIMEFRAME}</b>\n"
        f"⏱ Kontrol aralığı: {CHECK_INTERVAL}s\n"
        f"📐 ZigZag: {ZIGZAG_LEN} | Fib: {FIB_FACTOR}\n\n"
        "Zone'a giriş tespitinde alert alacaksın."
    )
    return send_telegram(msg)

# ─────────────────────────────────────────
# ALERT GEÇMİŞİ (tekrar alert önleme)
# ─────────────────────────────────────────

def load_sent_alerts() -> set:
    if os.path.exists(SENT_ALERTS_FILE):
        try:
            with open(SENT_ALERTS_FILE) as f:
                data = json.load(f)
                return set(data)
        except:
            pass
    return set()

def save_sent_alert(alert_id: str, sent: set):
    sent.add(alert_id)
    # Max 500 kayıt tut
    if len(sent) > 500:
        sent = set(list(sent)[-300:])
    try:
        with open(SENT_ALERTS_FILE, "w") as f:
            json.dump(list(sent), f)
    except:
        pass
    return sent

# ─────────────────────────────────────────
# VERİ ÇEKİMİ
# ─────────────────────────────────────────

def fetch_data() -> pd.DataFrame:
    """
    Kraken REST API — GitHub Actions'tan sorunsuz çalışır.
    API key gerektirmez, coğrafi kısıt yok, 720 mum/istek.
    """
    url          = "https://api.kraken.com/0/public/OHLC"
    interval_map = {"1h": 60, "15m": 15, "4h": 240}
    interval     = interval_map.get(TIMEFRAME, 60)
    target       = LOOKBACK_MONTHS * 30 * 24
    all_rows     = []
    since        = None  # ilk çağrıda en eski veriyi çeker

    # Kraken'da since=0 → en eskiden başlar, her seferinde 720 mum ilerler
    since = int((datetime.now(timezone.utc).timestamp() - LOOKBACK_MONTHS * 30 * 24 * 3600))

    for _ in range(20):  # max 20 istek = ~14400 mum
        params = {"pair": "XBTUSDT", "interval": interval, "since": since}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("error"):
            raise RuntimeError(f"Kraken hatası: {data['error']}")

        result = data["result"]
        pair   = [k for k in result.keys() if k != "last"][0]
        rows   = result[pair]

        if not rows:
            break

        all_rows.extend(rows)
        since = int(result["last"])  # sonraki batch için

        if len(all_rows) >= target:
            break
        if len(rows) < 720:
            break
        time.sleep(1)  # rate limit

    if not all_rows:
        raise RuntimeError("Kraken'dan veri alınamadı!")

    df = pd.DataFrame(all_rows, columns=["ts","o","h","l","c","vwap","v","count"])
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    for col in ["o","h","l","c","v"]:
        df[col] = df[col].astype(float)
    df = (df[["ts","o","h","l","c","v"]]
          .drop_duplicates("ts")
          .sort_values("ts")
          .reset_index(drop=True))
    log.info(f"Kraken'dan {len(df)} mum çekildi. Son fiyat: ${df['c'].iloc[-1]:,.2f}")
    return df

def calc_atr(df, period=14):
    hl = df["h"] - df["l"]
    hc = (df["h"] - df["c"].shift()).abs()
    lc = (df["l"] - df["c"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()

def compute_zigzag_msb(df: pd.DataFrame) -> list:
    """
    Pine Script logic'ini numpy ile hesaplar.
    Dönen liste: aktif zone'ların listesi
    Her zone: {
        direction: 'bull' | 'bear',
        top: float,
        bottom: float,
        msb_bar: int,
        bb_type: 'BB' | 'MB',
        active: bool,
        zone_id: str,
    }
    """
    n = len(df)
    H = df["h"].values
    L = df["l"].values
    O = df["o"].values
    C = df["c"].values
    zl = ZIGZAG_LEN

    # ── Trend tespiti (Pine: to_up / to_down) ──
    # to_up[i]   = H[i] == max(H[i-zl:i+1])
    # to_down[i] = L[i] == min(L[i-zl:i+1])
    to_up   = np.zeros(n, dtype=bool)
    to_down = np.zeros(n, dtype=bool)
    for i in range(zl, n):
        to_up[i]   = H[i] >= np.max(H[max(0,i-zl):i+1])
        to_down[i] = L[i] <= np.min(L[max(0,i-zl):i+1])

    trend = np.ones(n, dtype=int)
    for i in range(1, n):
        trend[i] = trend[i-1]
        if trend[i-1] == 1 and to_down[i]:
            trend[i] = -1
        elif trend[i-1] == -1 and to_up[i]:
            trend[i] = 1

    # ── Swing point'leri topla ──
    high_points = []  # (value, bar_index)
    low_points  = []  # (value, bar_index)

    for i in range(1, n):
        if trend[i] != trend[i-1]:
            if trend[i] == 1:
                # trend yukarı döndü → son low'u bul
                # Pine: last_trend_up_since = barssince(to_up)
                # low_val = lowest(last_trend_up_since)
                # Burada son to_up'tan bu yana en düşük low buluyoruz
                last_up = 0
                for k in range(i-1, -1, -1):
                    if to_up[k]:
                        last_up = k
                        break
                window_low = L[last_up:i+1]
                if len(window_low) > 0:
                    lv = np.min(window_low)
                    li = last_up + int(np.argmin(window_low))
                    low_points.append((lv, li, i))  # (value, price_bar, trend_change_bar)

            elif trend[i] == -1:
                # trend aşağı döndü → son high'ı bul
                last_down = 0
                for k in range(i-1, -1, -1):
                    if to_down[k]:
                        last_down = k
                        break
                window_high = H[last_down:i+1]
                if len(window_high) > 0:
                    hv = np.max(window_high)
                    hi = last_down + int(np.argmax(window_high))
                    high_points.append((hv, hi, i))

    # ── MSB hesapla ──
    zones = []

    # Market state takibi
    market = 1
    last_l0 = None
    last_h0 = None

    for idx in range(2, min(len(high_points), len(low_points)) + 1):
        try:
            h0v, h0i, h0tb = high_points[-1]
            h1v, h1i, h1tb = high_points[-2] if len(high_points) >= 2 else (None, None, None)
            l0v, l0i, l0tb = low_points[-1]
            l1v, l1i, l1tb = low_points[-2] if len(low_points) >= 2 else (None, None, None)
        except:
            break

        if None in [h1v, l1v]:
            break

    # Tüm trend kırılma noktalarında MSB kontrol et
    for ti in range(2, n):
        if trend[ti] == trend[ti-1]:
            continue

        # Bu anki swing point'leri bul
        hp = [p for p in high_points if p[2] <= ti]
        lp = [p for p in low_points  if p[2] <= ti]

        if len(hp) < 2 or len(lp) < 2:
            continue

        h0v, h0i, _ = hp[-1]
        h1v, h1i, _ = hp[-2]
        l0v, l0i, _ = lp[-1]
        l1v, l1i, _ = lp[-2]

        # MSB koşulu (Pine: market değişimi)
        new_market = market
        if market == 1 and l0v < l1v and l0v < l1v - abs(h0v - l1v) * FIB_FACTOR:
            new_market = -1
        elif market == -1 and h0v > h1v and h0v > h1v + abs(h1v - l0v) * FIB_FACTOR:
            new_market = 1

        if new_market == market:
            continue
        market = new_market

        # ── BULLISH MSB ──
        if market == 1:
            # OB: h1→l0 arasındaki son BEARISH mum
            ob_bar = None
            search_start = min(h1i, l0i)
            search_end   = max(h1i, l0i)
            for b in range(search_end, search_start - 1, -1):
                if b < n and O[b] > C[b]:  # bearish
                    ob_bar = b
                    break

            # BB/MB: l1→h1 arasındaki son BULLISH mum
            bb_bar = None
            bb_search_start = min(l1i, h1i)
            bb_search_end   = max(l1i, h1i)
            for b in range(bb_search_end, bb_search_start - 1, -1):
                if b < n and O[b] < C[b]:  # bullish
                    bb_bar = b
                    break

            bb_type = "BB" if l0v < l1v else "MB"

            if ob_bar is not None and bb_bar is not None:
                ob_top    = H[ob_bar]
                ob_bottom = L[ob_bar]
                bb_top    = H[bb_bar]
                bb_bottom = L[bb_bar]
                inter_top    = min(ob_top, bb_top)
                inter_bottom = max(ob_bottom, bb_bottom)

                if inter_top > inter_bottom:
                    zone_id = f"bull_{ti}_{round(inter_bottom)}_{round(inter_top)}"
                    zones.append({
                        "direction":   "bull",
                        "top":         inter_top,
                        "bottom":      inter_bottom,
                        "msb_bar":     ti,
                        "msb_price":   h1v,
                        "bb_type":     bb_type,
                        "zone_id":     zone_id,
                        "active":      True,
                        "ts":          df["ts"].iloc[min(ti, n-1)],
                    })

        # ── BEARISH MSB ──
        elif market == -1:
            # OB: l1→h0 arasındaki son BULLISH mum
            ob_bar = None
            search_start = min(l1i, h0i)
            search_end   = max(l1i, h0i)
            for b in range(search_end, search_start - 1, -1):
                if b < n and O[b] < C[b]:  # bullish
                    ob_bar = b
                    break

            # BB/MB: h1→l1 arasındaki son BEARISH mum
            bb_bar = None
            bb_search_start = min(h1i, l1i)
            bb_search_end   = max(h1i, l1i)
            for b in range(bb_search_end, bb_search_start - 1, -1):
                if b < n and O[b] > C[b]:  # bearish
                    bb_bar = b
                    break

            bb_type = "BB" if h0v > h1v else "MB"

            if ob_bar is not None and bb_bar is not None:
                ob_top    = H[ob_bar]
                ob_bottom = L[ob_bar]
                bb_top    = H[bb_bar]
                bb_bottom = L[bb_bar]
                inter_top    = min(ob_top, bb_top)
                inter_bottom = max(ob_bottom, bb_bottom)

                if inter_top > inter_bottom:
                    zone_id = f"bear_{ti}_{round(inter_bottom)}_{round(inter_top)}"
                    zones.append({
                        "direction":   "bear",
                        "top":         inter_top,
                        "bottom":      inter_bottom,
                        "msb_bar":     ti,
                        "msb_price":   l1v,
                        "bb_type":     bb_type,
                        "zone_id":     zone_id,
                        "active":      True,
                        "ts":          df["ts"].iloc[min(ti, n-1)],
                    })

    return zones

# ─────────────────────────────────────────
# ZONE GİRİŞ KONTROLÜ
# ─────────────────────────────────────────

def check_zone_entry(zones: list, current_price: float, atr: float) -> list:
    """
    Mevcut fiyatın hangi zone'lara girdiğini döner.
    Tolerans: ENTRY_TOLERANCE * ATR
    """
    tolerance = atr * ENTRY_TOLERANCE
    triggered = []
    for z in zones:
        if not z["active"]:
            continue
        top    = z["top"]    + tolerance
        bottom = z["bottom"] - tolerance
        if bottom <= current_price <= top:
            triggered.append(z)
    return triggered

# ─────────────────────────────────────────
# TELEGRAM MESAJ FORMATI
# ─────────────────────────────────────────

def format_zone_line(z: dict, current_price: float) -> str:
    """Tek zone için kısa özet satırı."""
    is_bull  = z["direction"] == "bull"
    emoji    = "🟢" if is_bull else "🔴"
    tag      = f"{'Bull' if is_bull else 'Bear'} OB-{z['bb_type']}"
    dist     = current_price - z["bottom"] if is_bull else z["top"] - current_price
    dist_pct = dist / current_price * 100
    arrow    = "⬆️" if is_bull else "⬇️"
    return (
        f"{emoji} <b>{tag}</b>  {arrow}\n"
        f"   ${z['bottom']:,.0f} — ${z['top']:,.0f}\n"
        f"   Uzaklık: ${abs(dist):,.0f}  (%{abs(dist_pct):.1f})"
    )

def format_zone_summary(zones: list, current_price: float) -> str:
    """Her çalışmada aktif zone'ların listesini göster."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    bulls = [z for z in zones if z["direction"] == "bull"]
    bears = [z for z in zones if z["direction"] == "bear"]

    lines = [
        f"📊 <b>{DISPLAY_SYMBOL} {TIMEFRAME} — Aktif Zone'lar</b>",
        f"⏰ {now}",
        f"💰 Fiyat: <b>${current_price:,.2f}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if bulls:
        lines.append("🟢 <b>BULL Zone'ları</b>")
        for z in sorted(bulls, key=lambda x: x["top"], reverse=True):
            lines.append(format_zone_line(z, current_price))
    else:
        lines.append("🟢 Bull zone yok")

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if bears:
        lines.append("🔴 <b>BEAR Zone'ları</b>")
        for z in sorted(bears, key=lambda x: x["top"], reverse=True):
            lines.append(format_zone_line(z, current_price))
    else:
        lines.append("🔴 Bear zone yok")

    return "\n".join(lines)

def format_alert(zone: dict, current_price: float) -> str:
    """Fiyat zone'a girince gönderilen uyarı mesajı."""
    is_bull  = zone["direction"] == "bull"
    emoji    = "🚨🟢" if is_bull else "🚨🔴"
    dir_str  = "BULL" if is_bull else "BEAR"
    action   = "LONG" if is_bull else "SHORT"
    tag      = f"{dir_str} OB-{zone['bb_type']}"
    zone_size= zone["top"] - zone["bottom"]
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Fiyatın zone içindeki konumu (%)
    pos_pct  = (current_price - zone["bottom"]) / zone_size * 100

    msg = (
        f"{emoji} <b>ZONE GİRİŞİ — {tag}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>{DISPLAY_SYMBOL} {TIMEFRAME}</b>  |  {now}\n\n"
        f"💰 <b>Fiyat:</b> ${current_price:,.2f}\n"
        f"📈 <b>Zone Üst:</b> ${zone['top']:,.2f}\n"
        f"📉 <b>Zone Alt:</b> ${zone['bottom']:,.2f}\n"
        f"📐 <b>Zone Genişliği:</b> ${zone_size:,.2f}\n"
        f"📍 <b>Zone içi konum:</b> %{pos_pct:.0f}\n\n"
        f"⚡ <b>{action} fırsatı!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Zone oluşum: {str(zone['ts'])[:16]}"
    )
    return msg

# ─────────────────────────────────────────
# ANA DÖNGÜ
# ─────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("MSB Alert Bot başlıyor...")
    log.info(f"Sembol: {DISPLAY_SYMBOL} | Timeframe: {TIMEFRAME}")
    log.info(f"Kontrol aralığı: {CHECK_INTERVAL}s")
    log.info("=" * 55)

    # Bot testi
    if not test_telegram():
        log.warning("Telegram bağlantısı kurulamadı! Token ve Chat ID'yi kontrol et.")
        log.warning("Devam ediliyor, alertler loglanacak...")

    sent_alerts = load_sent_alerts()

    # GitHub Actions cron her 5 dk tetikler — tek seferlik çalışır
    try:
        log.info("Veri çekiliyor...")
        df = fetch_data()
        log.info(f"{len(df)} mum yüklendi.")

        atr_series    = calc_atr(df, 14)
        current_atr   = atr_series.iloc[-1]
        current_price = float(df["c"].iloc[-1])
        log.info(f"Mevcut fiyat: ${current_price:,.2f} | ATR: ${current_atr:,.2f}")

        zones = compute_zigzag_msb(df)
        log.info(f"Toplam zone: {len(zones)} (Bull: {sum(1 for z in zones if z['direction']=='bull')} | Bear: {sum(1 for z in zones if z['direction']=='bear')})")

        for z in (zones[-10:] if len(zones) >= 10 else zones):
            log.info(f"  [{z['direction'].upper():4s}] {z['bb_type']} | ${z['bottom']:,.0f} - ${z['top']:,.0f}")

        # Her çalışmada aktif zone listesini Telegram'a gönder
        if zones:
            summary_id = f"summary_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
            if summary_id not in sent_alerts:
                summary_msg = format_zone_summary(zones, current_price)
                if send_telegram(summary_msg):
                    sent_alerts = save_sent_alert(summary_id, sent_alerts)

        triggered = check_zone_entry(zones, current_price, current_atr)

        if triggered:
            log.info(f"{len(triggered)} zone tetiklendi!")
            for zone in triggered:
                zid = zone["zone_id"]
                if zid in sent_alerts:
                    log.info(f"  [{zid}] zaten gönderildi, atlanıyor.")
                    continue
                msg = format_alert(zone, current_price)
                if send_telegram(msg):
                    sent_alerts = save_sent_alert(zid, sent_alerts)
                    log.info(f"  Alert gönderildi: {zid}")
                else:
                    log.error("  Telegram gönderilemedi!")
        else:
            log.info("Aktif zone girişi yok.")

    except Exception as e:
        log.error(f"Hata: {e}", exc_info=True)
        send_telegram(f"⚠️ <b>MSB Bot Hatası</b>\n\n<code>{str(e)[:200]}</code>")

if __name__ == "__main__":
    main()
