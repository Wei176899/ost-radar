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
from .compare import group as group_offers
from .classify import (FORMAT_LABEL, Franchises, detect_format, detect_kind, detect_sub, detect_tags,
                       disc_count, is_japanese, is_relevant)
from .models import ORDER, OUT, PRE, SOURCE_META, STATUSES, STOCK, TODAY, TW, UNKNOWN, Item
from .sources import SOURCES, Source, SourceDown

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
OUT_DIR = ROOT / "site" / "data"
CFG_PATH = Path(__file__).resolve().parent / "config.json"


def dump_lines(obj) -> str:
    """一筆資料一行的 JSON：仍是合法 JSON，但 git 只會記錄有變動的那幾行，repo 成長慢很多。"""
    one = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    nl = "\n"
    if isinstance(obj, list):
        return "[" + nl + ("," + nl).join(one(v) for v in obj) + nl + "]" + nl
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            if isinstance(v, dict) and len(v) > 20:  # 大型對照表（例如 state 的 items）逐筆換行
                inner = ("," + nl).join(one(kk) + ":" + one(vv) for kk, vv in v.items())
                parts.append(one(k) + ":{" + nl + inner + nl + "}")
            else:
                parts.append(one(k) + ":" + one(v))
        return "{" + nl + ("," + nl).join(parts) + nl + "}" + nl
    return one(obj) + nl


def health_check(rows: list[dict], prev_rows: list[dict], log) -> bool:
    """資料健康檢查：總筆數驟減代表多個通路同時改版或被封鎖，此時不覆蓋現有資料。"""
    if len(prev_rows) >= 500 and len(rows) < len(prev_rows) * 0.5:
        log(f"⚠ 健康檢查未通過：本次 {len(rows)} 筆，上次 {len(prev_rows)} 筆（減少超過一半），保留現有資料")
        return False
    return True


RANK = {PRE: 0, STOCK: 1, ORDER: 2, UNKNOWN: 3, OUT: 4}


def days_ago(iso: str) -> int:
    try:
        return (TODAY - datetime.strptime((iso or "")[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return 9999


def remember_checks(items: list[Item], state: dict, today: str) -> None:
    """記下每筆商品最後一次確認到的狀態，下次沒排到複查時沿用（也決定複查的輪替順序）。"""
    chk = state.setdefault("checks", {})
    for it in items:
        if it.verified and it.checked == today and SOURCES[it.source].verify is not Source.verify:
            chk[it.key] = {"d": today, "st": it.status, "r": it.release, "bc": it.barcode,
                           "q": it.stock, "n": it.note, "dl": it.deadline}
    for k in [k for k, v in chk.items() if days_ago(v.get("d", "")) > 45]:
        del chk[k]


def apply_checks(items: list[Item], state: dict, max_age: int) -> int:
    """本次沒排到複查的商品：套用近期的複查結果（狀態、發售日、條碼…），並保留當時的確認日期。"""
    chk, n = state.get("checks", {}), 0
    for it in items:
        c = chk.get(it.key)
        if it.verified or not c or days_ago(c.get("d", "")) > max_age:
            continue
        it.release = it.release or c.get("r", "")
        it.barcode = it.barcode or c.get("bc", "")
        it.deadline = it.deadline or c.get("dl", "")
        if it.status == UNKNOWN:  # 列表頁本身有狀態（現貨／售完）時以列表為準
            it.status = c.get("st", it.status)
            it.stock = c.get("q") if it.stock is None else it.stock
            it.note = it.note or c.get("n", "")
            it.verified, it.checked = True, c["d"]
            n += 1
    return n


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
        if src.marketplace and fmt_group == "movie":
            continue  # 拍賣只收日系作品，歐美電影原聲不在範圍
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
    if SOURCES[it.source].marketplace and "代購" not in it.tags and it.status == PRE:
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

    src.set_budget(float(src.cfg.get("search_budget_min", 25)))
    if src.catalog:
        for attempt in (1, 2):  # 分類頁是整批抓取：空結果多半是暫時性錯誤，稍候重試一次
            try:
                take(src.crawl(), "分類頁")
            except SourceDown:
                break
            except Exception as e:  # noqa: BLE001
                errors += 1
                log(f"  [{name}] 分類頁失敗: {e}")
            if found or attempt == 2 or src.down:
                break
            log(f"  [{name}] 分類頁沒有結果，60 秒後重試")
            time.sleep(60)
            src.fails = 0
    for n, q in enumerate(queries, 1):
        if src.down or time.monotonic() > src.deadline:
            src.down = src.down or "超過時間上限"
            log(f"  [{name}] 停止搜尋：{src.down}（完成 {n - 1}/{len(queries)}）")
            break
        try:
            take(src.search(q), q)
        except SourceDown:
            continue
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
            if (ost == OUT and it.status in (STOCK, PRE)) or (ost == ORDER and it.status == STOCK):
                events.append("補貨")
            if ost == PRE and it.status == STOCK:
                events.append("已到貨")
            if ost in (STOCK, PRE, ORDER) and it.status == OUT:
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
        "so": it.sold, "dl": it.deadline, "bc": it.barcode, "ck": it.checked,
    }


def carry_forward(rows: list[dict], prev_rows: list[dict], state: dict, prev_meta: dict, cfg: dict,
                  *, down: set[str], ran: set[str], flaky: set[str]) -> list[dict]:
    """把上次有、這次沒抓到的商品補回來。

    - 整個通路連不上（down）：全部沿用，避免網站上整個通路消失
    - 通路有跑但這筆沒出現：搜尋結果排名會浮動，grace_days 內先保留
    - 超過 stale_days 沒有確認：狀態改為「待確認」並註明上次狀態；超過 drop_days 移除
    """
    stale, drop, grace = (int(cfg.get("stale_days", 5)), int(cfg.get("drop_days", 30)),
                          int(cfg.get("grace_days", 2)))
    seen = state.get("items", {})
    fallback = (prev_meta.get("generated") or "")[:10]
    have = {r["id"] for r in rows}
    kept = []
    for r in prev_rows:
        s = r.get("s")
        if r.get("id") in have or s not in SOURCES or s not in ran:
            continue
        ck = (r.get("ck") or seen.get(r["id"], {}).get("last_seen") or fallback)[:10]
        age = days_ago(ck)
        if age > drop or (s not in down and (s not in flaky or age > grace)):
            continue
        r = {k: v for k, v in r.items() if k not in ("g", "gn", "best", "pick")}
        r["ck"] = ck
        if age >= stale and r.get("st") in (PRE, STOCK, ORDER):
            r["n"] = f"{ck[5:].replace('-', '/')} 為{r['st']}，之後未能更新，請至通路確認"
            r["st"], r["v"] = UNKNOWN, False
        kept.append(r)
    rows += kept
    return kept


def settle_status(rows: list[dict], today: str) -> None:
    """跨通路一致性：已過預定發售日一週、且今天沒有重新確認的預購，改為待確認。"""
    cutoff = (TODAY - timedelta(days=7)).isoformat()
    for r in rows:
        if r.get("st") == PRE and r.get("r") and r["r"] < cutoff and not (r.get("v") and r.get("ck") == today):
            r["st"] = UNKNOWN
            r["n"] = r.get("n") or "已過預定發售日，出貨狀態待確認"


def write_csv(rows: list[dict], path: Path):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["通路", "狀態", "已複查", "庫存", "格式", "類型", "作品", "標籤", "品名", "價格", "發售日",
                    "首次發現", "動態", "連結"])
        for r in rows:
            title = r["t"]
            if title[:1] in "=+-@":
                title = "'" + title  # 避免 Excel 把品名當公式執行（CSV injection）
            w.writerow([SOURCE_META.get(r["s"], {}).get("name", r["s"]), r["st"], "Y" if r["v"] else "",
                        r["q"] if r["q"] is not None else "", FORMAT_LABEL.get(r["f"], r["f"]),
                        f"{r['k']}/{r['sb']}", r["fr"], " ".join(r["tg"]), title, r["p"] or "", r["r"],
                        r["fs"], " ".join(r["fl"]), r["u"]])


def main():
    ap = argparse.ArgumentParser(description="動漫・遊戲原聲實體唱片追蹤器")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--merge", action="store_true", help="只更新指定通路，其餘通路沿用現有資料")
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
            src = next(s for s in srcs if s.key == k)
            if not found and not src.down:
                src.down = "本次未取得資料"  # 交給後面沿用上次資料；若上次也沒有就不影響
            results.update(found)
            log(f"  ✔ {SOURCE_META[k]['name']}：{len(found)} 筆（失敗 {err} 次）")

    today = now[:10]
    for it in results.values():  # 搜尋結果本身就含即時狀態的通路（API／列表頁庫存）
        if it.verified:
            it.checked = today
    if not args.no_verify:
        log("庫存複查…")
        limit = int(cfg.get("verify_limit_per_source", 500))
        chk = state.get("checks", {})

        def run_verify(s: Source):
            # 輪替：從未複查 → 最久沒複查的優先；這次查不完的下次接著查，數日內整個通路都會輪過一次
            mine = sorted((i for i in results.values() if i.source == s.key and not i.verified),
                          key=lambda i: (chk.get(i.key, {}).get("d", ""), not i.jp, RANK.get(i.status, 9)))
            if mine and not s.down:
                s.set_budget(float(cfg.get("verify_budget_min", 15)))
                try:
                    s.verify(mine, state, limit)
                except Exception as e:  # noqa: BLE001
                    log(f"  [{SOURCE_META[s.key]['name']}] 複查失敗: {e}")

        with ThreadPoolExecutor(max_workers=len(srcs) or 1) as ex:
            list(ex.map(run_verify, srcs))
        for it in results.values():
            if it.verified and not it.checked:
                it.checked = today

    items = list(results.values())
    remember_checks(items, state, today)
    reused = apply_checks(items, state, int(cfg.get("check_reuse_days", 7)))
    if reused:
        log(f"沿用近期複查結果 {reused} 筆")
    for it in items:
        it.checked = it.checked or today  # 未複查：以本次在列表上看到的日期為準
    apply_history(items, state, now)
    items.sort(key=lambda i: (i.release or "", i.first_seen), reverse=True)
    items.sort(key=lambda i: (not i.flags, RANK.get(i.status, 9), SOURCES[i.source].marketplace))

    if args.no_news:
        news = load_json(OUT_DIR / "news.json", [])  # 不更新新聞時保留現有內容
    else:
        log("收集發售新聞…")
        news = news_mod.collect(cfg, fr, log, load_json(OUT_DIR / "news.json", []))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.parent.mkdir(exist_ok=True)
    state["last_run"] = now
    rows = [to_row(i) for i in items]
    prev_meta = load_json(OUT_DIR / "meta.json", {})
    prev_rows = load_json(OUT_DIR / "items.json", [])
    down = {s.key: s.down for s in srcs if s.down}
    kept = carry_forward(rows, prev_rows, state, prev_meta, cfg,
                         down=set(down), ran={s.key for s in srcs},
                         flaky={s.key for s in srcs if errors.get(s.key) or s.partial or not s.catalog})
    if kept:
        log(f"沿用上次資料 {len(kept)} 筆" + ("：" + "、".join(
            f"{SOURCE_META[k]['name']}（{v}）" for k, v in down.items()) if down else ""))
    settle_status(rows, today)
    if args.merge:  # 未執行的通路完整保留
        rows += [r for r in prev_rows if r.get("s") not in enabled and r.get("s") in SOURCES]
    all_keys = [k for k, v in cfg.get("sources", {}).items() if v and k in SOURCES] if args.merge else enabled
    prev_src = {x["key"]: x for x in prev_meta.get("sources", [])}
    group_offers(rows, markets={k for k, c in SOURCES.items() if c.marketplace})  # 比價分組（含沿用的舊資料）
    rows.sort(key=lambda r: r["id"])  # 固定順序：每天的 diff 只會出現實際變動的商品（網站端自行排序）
    if not health_check(rows, prev_rows, log):
        sys.exit(2)  # 讓排程顯示失敗（GitHub 會寄通知），網站維持上一版資料
    STATE_PATH.write_text(dump_lines(state), encoding="utf-8")
    (OUT_DIR / "items.json").write_text(dump_lines(rows), encoding="utf-8")
    (OUT_DIR / "news.json").write_text(dump_lines(news), encoding="utf-8")
    write_csv(rows, OUT_DIR / "items.csv")
    count = lambda pred: sum(1 for r in rows if pred(r))  # noqa: E731
    meta = {
        "generated": now, "seconds": round(time.time() - t0),
        "total": len(rows), "news": len(news),
        "sources": [{"key": k, **SOURCE_META[k],
                     "count": sum(1 for r in rows if r["s"] == k),
                     "errors": errors.get(k, prev_src.get(k, {}).get("errors", 0)),
                     "down": down.get(k, "") if k in enabled else prev_src.get(k, {}).get("down", "")}
                    for k in all_keys],
        "status": {s: count(lambda r, s=s: r["st"] == s) for s in STATUSES},
        "stale": count(lambda r: days_ago(r.get("ck", "")) >= int(cfg.get("stale_days", 5))),
        "formats": {f: count(lambda r, f=f: r["f"] == f) for f in FORMAT_LABEL},
        "verified": count(lambda r: r["v"]),
        "franchises": sorted({r["fr"] for r in rows if r.get("fr")}),
        "links": cfg.get("links", []),
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"\n完成（{meta['seconds']} 秒）：{len(items)} 筆｜{meta['status']}｜{meta['formats']}｜"
        f"已複查 {meta['verified']}｜新聞 {len(news)}")
    flagged = [i for i in items if i.flags]
    for i in flagged[:20]:
        log(f"  [{' '.join(i.flags)}] {SOURCE_META[i.source]['name']} {i.status} {i.title[:60]}")


if __name__ == "__main__":
    main()
