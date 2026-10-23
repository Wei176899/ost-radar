"""比價：把不同通路的同一商品歸成一組，標出可購買的最低價。

配對順序：
1. 國際條碼相同 → 同一商品
2. 品名正規化後的關鍵詞相似（Jaccard），且格式、張數、版本（彩膠 / 一般）不衝突
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

# 店家裝飾與促銷字眼：比對時忽略
NOISE_RE = re.compile(
    r"【[^】]*】|\[[^\]]*(?:代購|預購|現貨|全新|免運)[^\]]*\]|"
    r"代購|代訂|預購|預訂|預約|現貨|全新|未拆|免運|限時|熱銷|正版|官方|進口|日版|日本|台壓|"
    r"黑膠唱片|黑膠|唱片|LP盤|アナログ盤|アナログ|レコード|vinyl|lp|cd|原聲帶|原聲|サウンドトラック|"
    r"soundtrack|original|o\.s\.t\.?|ost|限定盤|限定|初回|完全生産|完全生產|生産|生產|盤|版", re.I)
COLOR_RE = re.compile(r"彩膠|畫膠|colou?r|clear|splatter|marble|透明|picture|translucent", re.I)
BLACK_RE = re.compile(r"黑膠(?!唱片)|black vinyl", re.I)
DISCS_RE = re.compile(r"(\d)\s?(?:LP|CD)", re.I)
TOKEN_RE = re.compile(r"[a-z0-9]+|[぀-ヿ一-鿿]+")


def tokens(title: str) -> set[str]:
    t = NOISE_RE.sub(" ", title.lower())
    out: set[str] = set()
    for w in TOKEN_RE.findall(t):
        if w.isascii():
            if len(w) >= 2 and not w.isdigit():
                out.add(w)
            elif w.isdigit() and len(w) <= 2:  # 作品編號，例如 FF「15」、Vol.「2」
                out.add("#" + w)
        else:
            out.update(w[i:i + 2] for i in range(len(w) - 1)) if len(w) > 1 else out.add(w)
    return out


def edition(title: str) -> str:
    if COLOR_RE.search(title):
        return "color"
    if BLACK_RE.search(title):
        return "black"
    return ""


LIMITED_RE = re.compile(r"初回|限定|limited|deluxe|豪華|box", re.I)
NORMAL_RE = re.compile(r"通常盤|一般版|standard", re.I)
NUM_STRIP_RE = re.compile(r"\d+\s?(?:rpm|轉|g\b|克)|\d\s?(?:LP|CD|吋|寸|inch|\")|\b(?:19|20)\d{2}\b|\d{3,}|[A-Z]{2,}-?\d+", re.I)


def numbers(title: str) -> frozenset[str]:
    """作品編號 / 集數（例如 FF「15」、Vol.「2」、第「3」集），去掉張數、年份、型號後的 1～2 位數字。"""
    t = NUM_STRIP_RE.sub(" ", title)
    return frozenset(str(int(x)) for x in re.findall(r"(?<!\d)(?<!\d\.)(\d{1,2})(?!\d)(?!\.\d)", t))


def edition_tier(title: str) -> str:
    if NORMAL_RE.search(title):
        return "normal"
    if LIMITED_RE.search(title):
        return "limited"
    return ""


MARKETS: set[str] = set()  # 拍賣通路：同一商品常有多位賣家，可在同通路內合併


def compatible(a: dict, b: dict) -> bool:
    if a["f"] != b["f"]:
        return False
    if a["s"] == b["s"] and a["s"] not in MARKETS and not (a.get("bc") and a.get("bc") == b.get("bc")):
        return False  # 同一家商店不會重複上架同一商品
    da, db = DISCS_RE.search(a["t"]), DISCS_RE.search(b["t"])
    if da and db and da.group(1) != db.group(1):
        return False
    ea, eb = edition(a["t"]), edition(b["t"])
    if ea and eb and ea != eb:
        return False
    if a.get("fr") and b.get("fr") and a["fr"] != b["fr"]:
        return False
    if numbers(a["t"]) != numbers(b["t"]):  # 不同集數 / 續作
        return False
    ta, tb = edition_tier(a["t"]), edition_tier(b["t"])
    if ta and tb and ta != tb:  # 通常盤 vs 初回限定盤
        return False
    return True


def group(rows: list[dict], threshold: float = 0.62, markets: set[str] | None = None) -> None:
    """就地寫入 g（組別 id）、gn（組內筆數）、best（是否為組內可購買最低價）。"""
    MARKETS.clear()
    MARKETS.update(markets or ())
    n = len(rows)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # 1) 條碼
    by_code: dict[str, int] = {}
    for i, r in enumerate(rows):
        code = r.get("bc")
        if code:
            if code in by_code and compatible(rows[by_code[code]], r):
                union(by_code[code], i)
            else:
                by_code.setdefault(code, i)

    # 2) 品名相似：倒排索引找候選，只比較共用少見關鍵詞的組合
    toks = [tokens(r["t"]) for r in rows]
    index: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(toks):
        for t in ts:
            index[t].append(i)
    for i, ts in enumerate(toks):
        if len(ts) < 3:
            continue
        cand: dict[int, int] = defaultdict(int)
        for t in ts:
            post = index[t]
            if len(post) > 80:  # 太常見的詞不拿來配對
                continue
            for j in post:
                if j > i:
                    cand[j] += 1
        for j, shared in cand.items():
            if shared < 2 or not compatible(rows[i], rows[j]):
                continue
            tj = toks[j]
            sim = len(ts & tj) / len(ts | tj)
            if sim >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    for members in groups.values():
        gid = hashlib.sha1(min(rows[i]["id"] for i in members).encode()).hexdigest()[:10]
        # 可購買且價格合理（拍賣常有 1 元、外幣或誘餌價，低於 250 元不列入最低價）
        buyable = [i for i in members if rows[i]["st"] in ("現貨", "預購", "待確認") and (rows[i].get("p") or 0) >= 250]
        best = min(buyable, key=lambda i: (rows[i]["st"] != "現貨", rows[i]["p"]), default=None) if buyable else None
        low = min((rows[i]["p"] for i in buyable), default=None)
        for i in members:
            rows[i]["g"] = gid
            rows[i]["gn"] = len(members)
            rows[i]["best"] = bool(len(members) > 1 and low is not None and i in buyable and rows[i]["p"] == low)
        if best is not None and len(members) > 1:
            rows[best]["pick"] = True  # 組內推薦：有現貨優先，其次價格
