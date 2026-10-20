"""發售新聞：Google News RSS（日 / 中 / 英）＋ 海外遊戲動畫唱片廠牌的新品 / 預購（Shopify products.json）。"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

from .classify import ACG_STRONG_RE, Franchises, detect_format, is_japanese
from .models import TODAY, TW, clean, to_int
from .sources import UA

MEDIA_RE = re.compile(r"アナログ|レコード|\bLP\b|黑膠|vinyl|サントラ|サウンドトラック|原聲|soundtrack|\bOST\b|カセット|卡帶|"
                      r"cassette|\bCD\b|音楽集|ヴァイナル", re.I)
ANNOUNCE_RE = re.compile(r"発売決定|発売|リリース決定|予約|預購|發售|發行|release|pre-?order|announce", re.I)
CURRENCY = {"iam8bit.com": "USD", "www.lacedrecords.co": "GBP", "blackscreenrecords.com": "EUR",
            "www.spacelab9.com": "USD", "mondoshop.com": "USD"}


def _release_from_text(text: str, pub: datetime) -> str:
    """從標題抓「2026年12月17日」「12月17日発売」等日期。"""
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日", text) or re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})\s*(?:発売|發售|リリース)", text)
        if not m:
            return ""
        mo, d = map(int, m.groups())
        y = pub.year + (1 if mo < pub.month - 2 else 0)
    try:
        return datetime(y, mo, d).date().isoformat()
    except ValueError:
        return ""


def google_news(cfg: dict, fr: Franchises, log) -> list[dict]:
    out = {}
    keep = int(cfg.get("news", {}).get("keep_days", 120))
    for q in cfg.get("news", {}).get("google_news", []):
        hl, gl = q.get("hl", "ja"), q.get("gl", "JP")
        lang = hl.split("-")[0]
        url = (f"https://news.google.com/rss/search?q={quote(q['q'] + f' when:{keep}d')}"
               f"&hl={hl}&gl={gl}&ceid={gl}:{lang if lang != 'zh' else 'zh-Hant'}")
        try:
            time.sleep(1)
            root = ET.fromstring(requests.get(url, headers=UA, timeout=25).content)
        except Exception as e:  # noqa: BLE001
            log(f"  [新聞] Google News「{q['q']}」失敗: {e}")
            continue
        for it in root.iter("item"):
            raw = clean(it.findtext("title"))
            src = clean(it.findtext("source"))
            title = re.sub(rf"\s+-\s+{re.escape(src)}$", "", raw) if src else raw
            if not (MEDIA_RE.search(title) and (ACG_STRONG_RE.search(title) or fr.match(title))):
                continue
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(TW)
            except (TypeError, ValueError):
                continue
            if pub.date() < TODAY - timedelta(days=keep):
                continue
            key = re.sub(r"\W", "", title.lower())[:60]
            if key in out:
                continue
            franchise = fr.match(title) or ""
            out[key] = {
                "type": "news", "title": title, "url": it.findtext("link"), "source": src,
                "date": pub.date().isoformat(), "lang": lang,
                "release": _release_from_text(title, pub),
                "fmt": detect_format(title) or "", "franchise": franchise,
                "jp": is_japanese(title, franchise) or lang == "ja",
                "announce": bool(ANNOUNCE_RE.search(title)),
            }
    log(f"  [新聞] Google News：{len(out)} 則相關")
    return list(out.values())


def label_shops(cfg: dict, fr: Franchises, log) -> list[dict]:
    keep = int(cfg.get("news", {}).get("keep_days", 120))
    out = []
    for shop in cfg.get("news", {}).get("label_shops", []):
        host = shop["host"]
        try:
            time.sleep(1)
            prods = requests.get(f"https://{host}/products.json?limit=250", headers=UA, timeout=25).json()["products"]
        except Exception as e:  # noqa: BLE001
            log(f"  [新聞] {shop['name']} 失敗: {e}")
            continue
        n = 0
        for p in prods:
            title = clean(p.get("title"))
            tags = p.get("tags") or []
            tags = tags if isinstance(tags, list) else [t.strip() for t in str(tags).split(",")]
            meta = f"{title} {p.get('product_type', '')} {' '.join(tags)}"
            fmt = detect_format(meta)
            if not fmt:
                continue
            if not (ACG_STRONG_RE.search(meta) or fr.match(meta) or re.search(r"anime|game|soundtrack|OST", meta, re.I)):
                continue
            if re.search(r"digital|download|T-?Shirt|Poster|Figure|Pin|Hoodie|Shirt|Slipmat|Tote", meta, re.I) and fmt == "cd":
                continue
            pub = (p.get("published_at") or p.get("created_at") or "")[:10]
            if not pub or pub < (TODAY - timedelta(days=keep)).isoformat():
                continue
            v = (p.get("variants") or [{}])[0]
            pre = bool(re.search(r"pre-?order", meta, re.I))
            available = any(x.get("available") for x in p.get("variants") or [])
            franchise = fr.match(meta) or ""
            img = (p.get("images") or [{}])[0].get("src", "") if p.get("images") else ""
            out.append({
                "type": "label", "title": title, "url": f"https://{host}/products/{p.get('handle')}",
                "source": shop["name"], "date": pub, "lang": "en", "release": "",
                "fmt": fmt, "franchise": franchise, "jp": is_japanese(meta, franchise),
                "status": "預購" if pre and available else ("現貨" if available else "售完"),
                "price": to_int(v.get("price")), "currency": CURRENCY.get(host, "USD"),
                "image": img, "announce": pre,
            })
            n += 1
        log(f"  [新聞] {shop['name']}：{n} 項新品")
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿]", "", s.lower())


def dedupe_news(news: list[dict]) -> list[dict]:
    """同一則消息常有多家媒體、多語言報導：以『作品名』等括號內標題當主題，合併成一則並記錄相關報導數。"""
    pref = {"ja": 0, "zh": 1, "en": 2}
    keys: list[tuple[str, dict]] = []
    out: list[dict] = []
    for n in sorted(news, key=lambda n: (n["date"]), reverse=True):
        t = _norm(n["title"])
        cand = [_norm(x)[:10] for x in re.findall(r"[『「《【\"“]([^』」》】\"”]{3,40})", n["title"])]
        cand = [c for c in cand if len(c) >= 4]
        hit = next((d for k, d in keys if k in t), None)
        if hit is None:
            hit = next((d for c in cand for k, d in keys if c == k), None)
        if hit is not None:
            hit["related"] = hit.get("related", 0) + 1
            if pref.get(n["lang"], 3) < pref.get(hit["lang"], 3) and n["date"] >= hit["date"]:
                for f in ("title", "url", "source", "lang"):
                    hit[f] = n[f]
            hit["release"] = hit["release"] or n["release"]
            continue
        out.append(n)
        for c in cand:
            keys.append((c, n))
    return out


def collect(cfg: dict, fr: Franchises, log) -> list[dict]:
    gn = dedupe_news(google_news(cfg, fr, log))
    items = gn + label_shops(cfg, fr, log)
    items.sort(key=lambda x: x["date"], reverse=True)
    return items
