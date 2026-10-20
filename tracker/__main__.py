"""動漫・遊戲原聲實體唱片追蹤器

    python -m tracker                 完整執行（搜尋 → 分類 → 庫存複查 → 新聞 → 輸出網站資料）
    python -m tracker --quick         只跑一般關鍵字
    python -m tracker --only eslite,candlelight
    python -m tracker --no-news

輸出到 site/data/：items.json、news.json、meta.json、items.csv；歷史紀錄在 data/state.json。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from . import news as news_mod
from .classify import (FORMAT_LABEL, Franchises, detect_format, detect_kind, detect_sub, detect_tags,
                       disc_count, is_japanese, is_relevant)
from .models import OUT, PRE, SOURCE_META, STOCK, TODAY, TW, UNKNOWN, Item
from .sources import SOURCES, Source

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
OUT_DIR = ROOT / "site" / "data"
CFG_PATH = Path(__file__).resolve().parent / "config.json"


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def plan_queries(src: Source, cfg: dict, quick: bool) -> list[str]:
    if src.catalog:
        return []
    gq = cfg.get("generic_queries", {})
    qs: list[str] = []
    if src.bare_franchise:
        qs = [q for lst in gq.values() for q in lst]
        if not quick:
            qs += [d["aliases"][0] for d in cfg.get("franchises", {}).values()]
        return list(dict.fromkeys(qs))
    for fmt_group, lst in gq.items():
        if src.marketplace and fmt_group == "cd":
            qs += lst[:3]  # 拍賣的 CD 雜訊多，只跑前幾個
        else:
            qs += lst
    if not quick and not src.generic_only:
        suffix = cfg.get("franchise_query_suffix", {})
        groups = cfg.get("marketplace_formats", ["vinyl"]) if src.marketplace else list(suffix)
        for name, d in cfg.get("franchises", {}).items():
            alias = d["aliases"][0]
            for g in groups:
                if g == "cassette" and not src.marketplace:
                    continue  # 官方通路卡帶少，靠一般關鍵字與「原聲帶」查詢涵蓋
                qs.append(f"{alias} {suffix.get(g, '')}".strip())
    return list(dict.fromkeys(qs))


def classify(it: Item, fr: Franchises) -> bool:
    fmt = detect_format(it.title, it.fmt_hint)
    if not fmt:
        return False
    it.fmt = fmt
    it.discs = disc_count(it.title)
    it.franchise = fr.match(it.title) or (fr.match(it.extra) if it.is_ost else None) or ""
    text = f"{it.title} {it.extra}"
    it.kind = detect_kind(it.title if it.franchise else text, fr.kinds.get(it.franchise))
    it.sub = detect_sub(it.title)
    it.tags = detect_tags(f"{it.title} {it.note}")
    if it.source in ("ruten", "yahoo") and "代購" not in it.tags and it.status == PRE:
        it.tags.append("代購")
    it.jp = is_japanese(text, it.franchise or None)
    return True


def collect_source(src: Source, queries: list[str], fr: Franchises, log) -> tuple[dict[str, Item], int]:
    found: dict[str, Item] = {}
    errors = 0
    name = SOURCE_META[src.key]["name"]

    def take(results, q):
        for it in results:
            if not is_relevant(it.title, it.extra, fr, is_ost=it.is_ost, fmt_hint=it.fmt_hint):
                continue
            if it.key in found:
                found[it.key].queries.append(q)
                if it.status == PRE:
                    found[it.key].status = PRE
                continue
            if classify(it, fr):
                if src.marketplace and (not it.jp or it.status == OUT):
                    continue  # 拍賣只保留日系、可購買的，避免雜訊與資料量過大
                it.queries = [q]
                found[it.key] = it

    if src.catalog:
        try:
            take(src.crawl(), "分類頁")
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"  [{name}] 分類頁失敗: {e}")
    for n, q in enumerate(queries, 1):
        try:
            take(src.search(q), q)
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"  [{name}] 「{q}」失敗: {e}")
        if n % 40 == 0:
            log(f"  [{name}] {n}/{len(queries)}，目前 {len(found)} 筆")
    return found, errors


def apply_history(items: list[Item], state: dict, now: str) -> None:
    seen = state.setdefault("items", {})
    first_run = not seen
    today = now[:10]
    for it in items:
        old = seen.get(it.key)
        events = []
        if old is None:
            it.first_seen = now
            if not first_run:
                events.append("NEW")
                if it.status == PRE:
                    events.append("開放預購")
        else:
            it.first_seen = old.get("first_seen", now)
            ost = old.get("status")
            if ost == OUT and it.status in (STOCK, PRE):
                events.append("補貨")
            if ost == PRE and it.status == STOCK:
                events.append("已到貨")
            if ost in (STOCK, PRE) and it.status == OUT:
                events.append("售完")
            if old.get("price") and it.price and it.price < old["price"]:
                events.append(f"降價 {old['price']}→{it.price}")
        hist = (old or {}).get("events", [])
        hist = [e for e in hist if e["d"] >= (TODAY - timedelta(days=21)).isoformat()]
        hist += [{"d": today, "e": e} for e in events]
        it.flags = [e["e"] for e in hist if e["d"] >= (TODAY - timedelta(days=10)).isoformat()]
        seen[it.key] = {"first_seen": it.first_seen, "last_seen": now, "status": it.status,
                        "price": it.price, "title": it.title, "events": hist[-6:]}
    cutoff = (TODAY - timedelta(days=120)).isoformat()
    for k in [k for k, v in seen.items() if v.get("last_seen", "")[:10] < cutoff]:
        del seen[k]


CONTACT_RE = re.compile(
    r"(?<!\d)09\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"          # 手機
    r"|\(0\d{1,2}\)\s?\d{3,4}-?\d{4}(?!\d)|(?<![\w-])0\d{1,2}-\d{3,4}-?\d{4}(?!\d)"  # 市話（需有括號或連字號）
    r"|[\w.+-]+@[\w-]+\.[\w.]+"                              # email
    r"|(?i:line\s*(?:id)?\s*[:：@]\s*[\w.-]+)")               # LINE ID


def redact(s: str) -> str:
    """拍賣標題偶爾含賣家聯絡方式，公開前遮蔽。"""
    return CONTACT_RE.sub("〔已隱藏〕", s or "")


def safe_url(u: str) -> str:
    return u if isinstance(u, str) and u.startswith(("https://", "http://")) else ""


def to_row(it: Item) -> dict:
    return {
        "id": it.key, "s": it.source, "t": redact(it.title), "u": safe_url(it.url), "p": it.price,
        "st": it.status, "v": it.verified, "q": it.stock, "r": it.release, "i": safe_url(it.image),
        "n": redact(it.note), "sl": redact(it.seller),
        "f": it.fmt, "d": it.discs, "k": it.kind, "sb": it.sub, "tg": it.tags, "fr": it.franchise,
        "jp": it.jp, "fs": it.first_seen[:10], "fl": it.flags,
    }


def write_csv(items: list[Item], path: Path):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["通路", "狀態", "已複查", "庫存", "格式", "類型", "作品", "標籤", "品名", "價格", "發售日",
                    "首次發現", "動態", "連結"])
        for it in items:
            title = redact(it.title)
            if title[:1] in "=+-@":
                title = "'" + title  # 避免 Excel 把品名當公式執行（CSV injection）
            w.writerow([SOURCE_META[it.source]["name"], it.status, "Y" if it.verified else "", it.stock or "",
                        FORMAT_LABEL.get(it.fmt, it.fmt), f"{it.kind}/{it.sub}", it.franchise, " ".join(it.tags),
                        title, it.price or "", it.release, it.first_seen[:10], " ".join(it.flags), safe_url(it.url)])


def main():
    ap = argparse.ArgumentParser(description="動漫・遊戲原聲實體唱片追蹤器")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = ap.parse_args()
    lock = threading.Lock()

    def log(msg):
        with lock:
            print(msg, flush=True)

    t0 = time.time()
    cfg = load_json(CFG_PATH, {})
    fr = Franchises.from_config(cfg)
    enabled = [k for k, v in cfg.get("sources", {}).items() if v and k in SOURCES]
    if args.only:
        enabled = [k for k in args.only.split(",") if k in SOURCES]
    state = load_json(STATE_PATH, {})
    now = datetime.now(TW).strftime("%Y-%m-%d %H:%M")
    srcs = [SOURCES[k](cfg, log) for k in enabled]
    plans = {s.key: plan_queries(s, cfg, args.quick) for s in srcs}
    log(f"開始：{len(srcs)} 個通路，" + "、".join(f"{SOURCE_META[s.key]['name']} {len(plans[s.key])}" for s in srcs))

    results: dict[str, Item] = {}
    errors: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=len(srcs) or 1) as ex:
        futs = {s.key: ex.submit(collect_source, s, plans[s.key], fr, log) for s in srcs}
        for k, fut in futs.items():
            found, err = fut.result()
            errors[k] = err
            results.update(found)
            log(f"  ✔ {SOURCE_META[k]['name']}：{len(found)} 筆（失敗 {err} 次）")

    if not args.no_verify:
        log("庫存複查…")
        limit = int(cfg.get("verify_limit_per_source", 500))
        order = {PRE: 0, STOCK: 1, UNKNOWN: 2, OUT: 3}

        def run_verify(s: Source):
            mine = sorted((i for i in results.values() if i.source == s.key and not i.verified),
                          key=lambda i: (not i.jp, order.get(i.status, 9)))
            if mine:
                try:
                    s.verify(mine, state, limit)
                except Exception as e:  # noqa: BLE001
                    log(f"  [{SOURCE_META[s.key]['name']}] 複查失敗: {e}")

        with ThreadPoolExecutor(max_workers=len(srcs) or 1) as ex:
            list(ex.map(run_verify, srcs))

    items = list(results.values())
    apply_history(items, state, now)
    order = {PRE: 0, STOCK: 1, UNKNOWN: 2, OUT: 3}
    items.sort(key=lambda i: (i.release or "", i.first_seen), reverse=True)
    items.sort(key=lambda i: (not i.flags, order.get(i.status, 9), i.source in ("ruten", "yahoo")))

    news = []
    if not args.no_news:
        log("收集發售新聞…")
        news = news_mod.collect(cfg, fr, log)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.parent.mkdir(exist_ok=True)
    state["last_run"] = now
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT_DIR / "items.json").write_text(json.dumps([to_row(i) for i in items], ensure_ascii=False,
                                                   separators=(",", ":")), encoding="utf-8")
    (OUT_DIR / "news.json").write_text(json.dumps(news, ensure_ascii=False, separators=(",", ":")),
                                       encoding="utf-8")
    write_csv(items, OUT_DIR / "items.csv")
    count = lambda pred: sum(1 for i in items if pred(i))  # noqa: E731
    meta = {
        "generated": now, "seconds": round(time.time() - t0),
        "total": len(items), "news": len(news),
        "sources": [{"key": k, **SOURCE_META[k], "count": count(lambda i, k=k: i.source == k),
                     "errors": errors.get(k, 0)} for k in enabled],
        "status": {s: count(lambda i, s=s: i.status == s) for s in (PRE, STOCK, UNKNOWN, OUT)},
        "formats": {f: count(lambda i, f=f: i.fmt == f) for f in FORMAT_LABEL},
        "verified": count(lambda i: i.verified),
        "franchises": sorted({i.franchise for i in items if i.franchise}),
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"\n完成（{meta['seconds']} 秒）：{len(items)} 筆｜{meta['status']}｜{meta['formats']}｜"
        f"已複查 {meta['verified']}｜新聞 {len(news)}")
    flagged = [i for i in items if i.flags]
    for i in flagged[:20]:
        log(f"  [{' '.join(i.flags)}] {SOURCE_META[i.source]['name']} {i.status} {i.title[:60]}")


if __name__ == "__main__":
    main()
