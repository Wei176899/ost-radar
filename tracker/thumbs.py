"""封面縮圖：把各通路的封面下載一次、轉成小尺寸 WebP，放在網站同網域（site/img/）。

    python -m tracker.thumbs

- 檔名用原始網址的雜湊，已存在就不重抓（GitHub Actions 以快取保留）
- 同時算出主色，網頁在圖片載入前先用主色當底，避免一片灰
- 多張商品共用的同一張圖（通路的「無圖片」佔位圖）會被判定為無封面
- 輸出 site/img/map.json（商品 id → [縮圖, 主色]，0 = 無封面），網頁載入時合併；不改動 items.json
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "site" / "data" / "items.json"
IMG_DIR = ROOT / "site" / "img"
INDEX = IMG_DIR / "index.json"          # 網址雜湊 → {c: 主色, sig: 內容雜湊} 或 {bad: 1}
MAP = IMG_DIR / "map.json"
SIZE = 360                              # 卡片約 190px，2 倍螢幕剛好清晰
QUALITY = 72
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def key_of(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def fetch(url: str) -> dict:
    """下載並轉檔，回傳索引資料。失敗回傳 {bad: 1}（下次仍會重試）。"""
    k = key_of(url)
    try:
        r = requests.get(url, headers=UA, timeout=12)
        r.raise_for_status()
        raw = r.content
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im).convert("RGB")
        if min(im.size) < 40:
            return {"bad": 1, "retry": 0}
        im.thumbnail((SIZE, SIZE), Image.LANCZOS)
        # 置中裁成正方形以外的比例保留，網頁用 object-fit: cover
        avg = im.resize((1, 1), Image.BOX).getpixel((0, 0))
        im.save(IMG_DIR / f"{k}.webp", "WEBP", quality=QUALITY, method=5)
        return {"c": "#%02x%02x%02x" % avg, "sig": hashlib.md5(raw).hexdigest()[:12]}
    except Exception:  # noqa: BLE001
        return {"bad": 1, "retry": 1}


def main(workers: int = 16) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    t0 = time.time()
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    rows = json.loads(ITEMS.read_text(encoding="utf-8"))
    try:
        index = json.loads(INDEX.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        index = {}

    urls = {r["i"] for r in rows if r.get("i")}
    todo = [u for u in urls
            if key_of(u) not in index
            or index[key_of(u)].get("retry")
            or ("c" in index[key_of(u)] and not (IMG_DIR / f"{key_of(u)}.webp").exists())]
    print(f"封面 {len(urls)} 張，需下載 {len(todo)} 張")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for u, info in zip(todo, ex.map(fetch, todo)):
            index[key_of(u)] = info

    # 同一張圖被很多商品共用 → 通路的佔位圖，當作沒有封面
    sigs = Counter(v.get("sig") for k, v in index.items() if v.get("sig"))
    placeholders = {s for s, n in sigs.items() if n >= 8}

    used, ok, out = set(), 0, {}
    for r in rows:
        u = r.get("i")
        if not u:
            continue
        k = key_of(u)
        info = index.get(k, {})
        if info.get("sig") in placeholders:
            out[r["id"]] = 0  # 佔位圖：網頁改顯示文字封面
            continue
        if "c" in info and (IMG_DIR / f"{k}.webp").exists():
            out[r["id"]] = [k, info["c"]]
            used.add(k)
            ok += 1

    # 清掉已不再使用的縮圖，讓快取維持精簡
    removed = 0
    for f in IMG_DIR.glob("*.webp"):
        if f.stem not in used:
            f.unlink()
            removed += 1
    index = {k: v for k, v in index.items() if k in used or v.get("bad")}
    INDEX.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    MAP.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = sum(f.stat().st_size for f in IMG_DIR.glob("*.webp"))
    print(f"完成（{time.time() - t0:.0f} 秒）：縮圖 {ok} 張、佔位圖 {len(placeholders)} 種、"
          f"清除 {removed} 張，共 {size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
