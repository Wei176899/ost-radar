from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).date()

# 狀態
PRE, STOCK, OUT, UNKNOWN = "預購", "現貨", "缺貨", "待確認"

SOURCE_META = {
    "books": {"name": "博客來", "type": "書店電商", "home": "https://www.books.com.tw/"},
    "eslite": {"name": "誠品線上", "type": "書店電商", "home": "https://www.eslite.com/"},
    "pchome": {"name": "PChome 24h", "type": "綜合電商", "home": "https://24h.pchome.com.tw/"},
    "gmusic": {"name": "玫瑰大眾", "type": "唱片行", "home": "https://www.g-music.com.tw/"},
    "candlelight": {"name": "燭光唱片", "type": "唱片行", "home": "https://www.candlelightrecords.tw/"},
    "ruten": {"name": "露天拍賣", "type": "拍賣", "home": "https://www.ruten.com.tw/"},
    "yahoo": {"name": "Yahoo 拍賣", "type": "拍賣", "home": "https://tw.bid.yahoo.com/"},
}


@dataclass
class Item:
    source: str
    pid: str
    title: str
    url: str
    price: int | None = None
    status: str = UNKNOWN
    release: str = ""
    image: str = ""
    note: str = ""
    seller: str = ""
    fmt_hint: str | None = None
    is_ost: bool = False
    extra: str = ""            # 描述文字（只用於判斷，不輸出）
    verified: bool = False     # 是否已用商品頁 / 庫存 API 複查
    stock: int | None = None
    queries: list[str] = field(default_factory=list)
    # 分類（classify 後填入）
    fmt: str = ""
    discs: str = ""
    kind: str = ""
    sub: str = ""
    tags: list[str] = field(default_factory=list)
    franchise: str = ""
    jp: bool = False
    # 歷史
    first_seen: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.pid}"


def clean(s) -> str:
    s = html.unescape(str(s or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def to_int(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "").replace("$", "").strip()))
    except (TypeError, ValueError):
        return None


def norm_date(s) -> str:
    """2026/10/28、10/28/2026、2026-10-28T..、2027/01、Unix 時間戳 → 2026-10-28（只有年月時用 01 日）。"""
    if not s:
        return ""
    if isinstance(s, (int, float)) or (isinstance(s, str) and s.isdigit() and len(s) >= 9):
        try:
            return datetime.fromtimestamp(int(s), TW).date().isoformat()
        except (ValueError, OSError):
            return ""
    s = str(s)
    m = re.search(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
        if m:
            mo, d, y = m.groups()
        else:
            m = re.search(r"(\d{4})\s*[/.年-]\s*(\d{1,2})", s)
            if not m:
                return ""
            (y, mo), d = m.groups(), 1
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return ""


def is_future(iso: str) -> bool:
    return bool(iso) and iso > TODAY.isoformat()


PREORDER_RE = re.compile(r"預購|預定|預約|予約|代訂|預計.{0,8}(?:出貨|發售|到貨)|Pre-?order", re.I)


def title_says_preorder(t: str) -> bool:
    return bool(PREORDER_RE.search(t))
