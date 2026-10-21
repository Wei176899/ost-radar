"""各通路：搜尋 + 庫存複查。

每個通路實作：
    search(query) -> list[Item]     依關鍵字搜尋（有些通路改用 crawl）
    crawl() -> list[Item]           直接走分類頁（燭光唱片）
    verify(items, state, limit)     到商品頁 / 庫存 API 再確認狀態
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .models import (OUT, PRE, STOCK, UNKNOWN, Item, clean, is_future, norm_date,
                     title_says_preorder, to_int)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en;q=0.7",
}
MARKET_PRE_RE = re.compile(r"代購|代訂|日本代|空運|海運")


class SourceDown(Exception):
    """通路被判定無法連線或已超過時間上限，後續請求直接略過。"""


class Source:
    key = ""
    generic_only = False     # 只跑一般關鍵字
    marketplace = False      # 拍賣：作品關鍵字只跑黑膠 / 卡帶
    catalog = False          # 不用關鍵字，直接爬分類頁
    bare_franchise = False   # 作品關鍵字不加「黑膠」「原聲帶 CD」等後綴

    MAX_CONSECUTIVE_FAILS = 6   # 連續失敗這麼多次就判定此通路擋連線，停止嘗試

    def __init__(self, cfg: dict, log):
        self.cfg = cfg
        self.log = log
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.delay = float(cfg.get("request_delay_sec", 0.7))
        self.limit = int(cfg.get("results_per_query", 40))
        self.fails = 0
        self.down = ""            # 非空字串 = 已停止此通路的原因
        self.deadline = float("inf")

    def set_budget(self, minutes: float) -> None:
        """設定這個階段（搜尋或複查）最多可花的時間。"""
        self.deadline = time.monotonic() + minutes * 60

    def _req(self, method, url, retries=2, **kw):
        if self.down:
            raise SourceDown(self.down)
        if time.monotonic() > self.deadline:
            raise SourceDown("超過時間上限")
        last = None
        for attempt in range(retries):
            time.sleep(self.delay * (1 + attempt * 3))
            try:
                r = self.s.request(method, url, timeout=20, **kw)
                if r.status_code in (429, 502, 503) and attempt < retries - 1:
                    time.sleep(6)
                    last = r
                    continue
                r.raise_for_status()
                self.fails = 0
                return r
            except requests.HTTPError:
                self._failed()
                raise
            except (requests.ConnectionError, requests.Timeout) as e:
                last = e
                if attempt == retries - 1:
                    self._failed()
                    raise
        self._failed()
        if isinstance(last, requests.Response):
            last.raise_for_status()
        raise RuntimeError(f"request failed: {url}")

    def _failed(self) -> None:
        self.fails += 1
        if self.fails >= self.MAX_CONSECUTIVE_FAILS and not self.down:
            self.down = f"連續 {self.fails} 次連線失敗（可能封鎖海外連線）"

    def get(self, url, **kw):
        return self._req("GET", url, **kw)

    def post(self, url, **kw):
        return self._req("POST", url, **kw)

    def search(self, q: str) -> list[Item]:
        return []

    def crawl(self) -> list[Item]:
        return []

    def verify(self, items: list[Item], state: dict, limit: int) -> None:
        pass


# ======================================================================= 博客來
class Books(Source):
    key = "books"

    def search(self, q):
        r = self.get(f"https://search.books.com.tw/search/query/key/{quote(q)}/cat/all/sort/5")
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for td in soup.select(".table-td[id^=prod-itemlist-]")[: self.limit]:
            pid = td["id"].rsplit("-", 1)[-1]
            a = td.select_one("h4 a")
            if not a:
                continue
            ptype = clean(td.select_one(".type p").get_text()) if td.select_one(".type p") else ""
            if ptype and ptype not in ("CD", "DVD", "黑膠", "LP"):
                continue  # 書籍、3C 等
            title = clean(a.get("title") or a.get_text())
            price_b = td.select(".price b")
            img = td.select_one("img")
            image = (img.get("data-src") or img.get("src", "")) if img else ""
            out.append(Item("books", pid, title, f"https://www.books.com.tw/products/{pid}",
                            to_int(price_b[-1].get_text()) if price_b else None,
                            PRE if title_says_preorder(title) else UNKNOWN, image=image))
        return out

    def verify(self, items, state, limit):
        """發行日期：商品頁（有快取）；庫存：購物車資訊 AJAX（需瀏覽器，若安裝 Playwright 才會跑）。"""
        cache = state.setdefault("books_release", {})
        budget = int(self.cfg.get("books_detail_limit", 80))
        self.delay = max(self.delay, 1.5)
        fails = 0
        for it in items:
            if it.pid not in cache and budget > 0 and fails < 3:
                budget -= 1
                try:
                    r = self.get(it.url)
                    r.encoding = "utf-8"
                    m = re.search(r"發行日期[：:]\s*([\d/]+)", r.text)
                    cache[it.pid] = norm_date(m.group(1)) if m else ""
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    self.log(f"  [博客來] 商品頁失敗 {it.pid}: {e}")
            it.release = cache.get(it.pid, "")
            if is_future(it.release):
                it.status = PRE
        # 博客來的購物車區塊由瀏覽器端載入且有防機器人驗證，不做自動化庫存查詢
        for it in items:
            if it.status == UNKNOWN:
                it.note = "可訂購（博客來未提供庫存查詢）"


# ======================================================================= 誠品
class Eslite(Source):
    key = "eslite"

    def search(self, q):
        url = (f"https://athena.eslite.com/api/v2/search?q={quote(q)}"
               f"&size={self.limit}&start=0&sort=manufacturer_date+desc")
        data = self.get(url).json()
        out = []
        for h in data.get("hits", {}).get("hit", []):
            f = h.get("fields", {})
            cats = f.get("categories") or []
            mch = f.get("mch", "")
            if not mch.startswith("311") or mch.startswith("311XX"):
                continue  # 非音樂商品
            title = clean(f.get("name"))
            release = norm_date(f.get("manufacturer_date", ""))
            stock = to_int(f.get("stock")) or 0
            st = f.get("status", "")
            if st == "can_not_buy" or st == "not_add_to_notice":
                status = OUT
            elif is_future(release) or title_says_preorder(title):
                status = PRE
            elif st == "add_to_shopping_cart":
                status = STOCK if stock > 0 else UNKNOWN
            else:
                status = UNKNOWN
            photo = f.get("product_photo_url", "")
            it = Item("eslite", str(h.get("id")), title,
                      f.get("url") or f"https://www.eslite.com/product/{h.get('id')}",
                      to_int(f.get("final_price")), status, release,
                      photo if photo.startswith("http") else (f"https://s.eslite.com{photo}" if photo else ""),
                      seller=" / ".join(f.get("author", [])[:2]))
            it.stock = stock
            it.extra = clean(f.get("description", ""))[:500]
            it.fmt_hint = "vinyl" if "15442" in cats else "cd"
            it.is_ost = "15454" in cats
            out.append(it)
        return out

    def verify(self, items, state, limit):
        n = 0
        for it in items[:limit]:
            try:
                d = self.get(f"https://athena.eslite.com/api/v1/products/{it.pid}").json()
            except Exception as e:  # noqa: BLE001
                self.log(f"  [誠品] 複查失敗 {it.pid}: {e}")
                continue
            n += 1
            it.verified = True
            it.stock = to_int(d.get("stock"))
            it.release = norm_date(d.get("manufacturer_date", "")) or it.release
            it.price = to_int(d.get("final_price")) or it.price
            btn = d.get("product_button_status") or ""
            mode = (d.get("sale_mode_text") or d.get("sale_mode") or "") or ""
            lv3 = d.get("level3_name") or ""
            if "原聲" in lv3 or "配樂" in lv3:
                it.is_ost = True
            if "預購" in str(mode) or (is_future(it.release) and btn == "add_to_shopping_cart"):
                it.status = PRE
            elif btn == "add_to_shopping_cart":
                it.status = STOCK if (it.stock or 0) > 0 else UNKNOWN
                if not it.stock:
                    it.note = "可下單（需調貨）"
            else:
                it.status = OUT
        self.log(f"  [誠品] 已複查 {n} 筆")


# ======================================================================= PChome
class PChome(Source):
    key = "pchome"
    generic_only = True

    def search(self, q):
        data = self.get(f"https://ecshweb.pchome.com.tw/search/v3.3/all/results?q={quote(q)}&page=1").json()
        out = []
        for p in (data.get("prods") or [])[: self.limit]:
            pic = p.get("picB") or p.get("picS") or ""
            it = Item("pchome", p["Id"], clean(p.get("name")), f"https://24h.pchome.com.tw/prod/{p['Id']}",
                      to_int(p.get("price")), UNKNOWN, norm_date(p.get("publishDate", "")),
                      f"https://cs-a.ecimg.tw{pic}" if pic else "")
            it.extra = clean(p.get("describe", ""))[:400]
            out.append(it)
        return out

    def verify(self, items, state, limit):
        ids = [it.pid for it in items]
        by = {it.pid: it for it in items}
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            try:
                rows = self.get("https://ecapi.pchome.com.tw/ecshop/prodapi/v2/prod/button&id="
                                + ",".join(chunk) + "&fields=Id,Price,Qty,ButtonType,SaleStatus").json()
            except Exception as e:  # noqa: BLE001
                self.log(f"  [PChome] 庫存查詢失敗: {e}")
                continue
            info = {}
            for row in rows:
                base = row["Id"].rsplit("-", 1)[0]
                if base not in info or row.get("ButtonType") == "ForSale":
                    info[base] = row
            for pid in chunk:
                it, row = by[pid], info.get(pid)
                if not row:
                    continue
                it.verified = True
                it.stock = to_int(row.get("Qty"))
                bt = row.get("ButtonType", "")
                if bt == "ForSale":
                    it.status = PRE if (title_says_preorder(it.title) or is_future(it.release)) else STOCK
                elif bt in ("SoldOut", "NotReady", "OrderRefill", "Discontinued"):
                    it.status = OUT
                p = (row.get("Price") or {}).get("P")
                if p:
                    it.price = to_int(p)


# ======================================================================= 玫瑰大眾
class GMusic(Source):
    key = "gmusic"
    bare_franchise = True  # 站內搜尋是 AND 比對，只用作品名搜尋才找得到

    def search(self, q):
        out = []
        for page in (1, 2, 3, 4):
            d = self.post("https://www.g-music.com.tw/search/search.json", json={"q": q, "page": page},
                          headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}).json()
            prods = d.get("products", {})
            for p in prods.get("result", []):
                title = clean(p.get("title"))
                v = (p.get("variants") or [{}])[0]
                qty = to_int(v.get("inventory_quantity"))
                release = norm_date(p.get("slogan") or "")
                img = (p.get("featured_image") or {}).get("large") or ""
                if p.get("in_stock") and is_future(release):
                    status = PRE
                elif p.get("in_stock"):
                    status = STOCK
                else:
                    status = OUT
                if title_says_preorder(title) and p.get("in_stock"):
                    status = PRE
                it = Item("gmusic", str(p["id"]), title,
                          f"https://www.g-music.com.tw/products/{quote(p.get('handle') or str(p['id']))}",
                          to_int(v.get("price")), status, release,
                          ("https:" + img) if img.startswith("//") else img,
                          seller=clean(p.get("vendor")))
                it.stock = qty
                it.verified = True  # 搜尋 API 直接回傳即時庫存
                it.extra = clean(p.get("brief"))
                it.fmt_hint = "cd"
                it.is_ost = bool(re.search(r"原聲|OST|Soundtrack", f"{title} {it.extra}", re.I))
                out.append(it)
            if page >= (prods.get("total_pages") or 1) or len(out) >= self.limit:
                break
        return out


# ======================================================================= 燭光唱片
CANDLE_CATS = {
    # 分類 id: (格式提示, 是否原聲帶分類, 額外標籤)
    "163410": ("vinyl", True, ""), "163553": ("vinyl", True, ""), "163860": ("7inch", True, ""),
    "163456": ("cd", True, ""), "163718": ("cassette", True, ""), "159866": (None, False, "pre"),
    "163406": ("vinyl", False, ""), "176775": ("7inch", False, ""), "163736": ("cd", False, ""),
}


class Candlelight(Source):
    key = "candlelight"
    catalog = True

    def crawl(self):
        out: dict[str, Item] = {}
        for cat, (hint, ost, extra) in CANDLE_CATS.items():
            prev_ids: set[str] = set()
            for page in range(1, 40):
                try:
                    r = self.get(f"https://www.candlelightrecords.tw/category/{cat}?page={page}")
                except Exception as e:  # noqa: BLE001
                    self.log(f"  [燭光] 分類 {cat} 第 {page} 頁失敗: {e}")
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                lis = soup.select("ul.js_product_block > li")
                ids = {a["href"].rstrip("/").rsplit("/", 1)[-1] for a in soup.select("a.pt_items_block")}
                if not lis or ids <= prev_ids:
                    break  # 沒有下一頁（超過最後一頁會重複顯示）
                prev_ids = ids
                for li in lis:
                    a = li.select_one("a.pt_items_block")
                    if not a:
                        continue
                    pid = a["href"].rstrip("/").rsplit("/", 1)[-1]
                    if pid in out:
                        if extra == "pre":
                            out[pid].status = PRE
                        continue
                    ph = li.select_one(".pt_photo")
                    title = clean(ph.get("title") if ph else a.get_text())
                    img = ""
                    if ph and ph.get("style"):
                        m = re.search(r"url\(([^)]+)\)", ph["style"])
                        img = m.group(1).strip("'\"") if m else ""
                    txt = li.get_text(" ", strip=True)
                    m = re.search(r"\$\s?([\d,]+)", txt)
                    status = OUT if "已售完" in txt else (PRE if extra == "pre" else STOCK)
                    href = a["href"].replace("/en/", "/")
                    if href.startswith("/"):
                        href = "https://www.candlelightrecords.tw" + href
                    it = Item("candlelight", pid, title, href,
                              to_int(m.group(1)) if m else None, status, image=img)
                    it.fmt_hint, it.is_ost = hint, ost
                    out[pid] = it
        return list(out.values())

    def verify(self, items, state, limit):
        n = 0
        for it in items[:limit]:
            try:
                txt = BeautifulSoup(self.get(it.url).text, "html.parser").get_text(" ", strip=True)
            except Exception as e:  # noqa: BLE001
                self.log(f"  [燭光] 複查失敗 {it.pid}: {e}")
                continue
            n += 1
            it.verified = True
            m = re.search(r"預計[：:]\s*(\d{4}/\d{1,2}(?:/\d{1,2})?)\s*出貨", txt)
            if m or "我要預購" in txt:
                it.status = PRE
                if m:
                    parts = m.group(1).split("/")
                    it.release = (norm_date(m.group(1)) if len(parts) == 3
                                  else f"{parts[0]}-{int(parts[1]):02d}")  # 只有年月就保留年月
                    it.note = f"預計 {m.group(1)} 出貨"
            elif re.search(r"選擇規格\s*-已售完", txt):
                it.status = OUT
            elif "立即購買" in txt or "加入購物車" in txt:
                it.status = STOCK
        self.log(f"  [燭光] 已複查 {n} 筆")


# ======================================================================= 露天
class Ruten(Source):
    key = "ruten"
    marketplace = True

    def search(self, q):
        rows = self.get(f"https://rtapi.ruten.com.tw/api/search/v3/index.php/core/prod?q={quote(q)}"
                        f"&type=direct&sort=new/dc&offset=1&limit={self.limit}").json().get("Rows", [])
        ids = [r["Id"] for r in rows]
        out = []
        for i in range(0, len(ids), 30):
            detail = self.get("https://rtapi.ruten.com.tw/api/prod/v2/index.php/prod?id="
                              + ",".join(ids[i:i + 30])).json()
            for d in detail:
                title = clean(d.get("ProdName"))
                qty = to_int(d.get("StockQty")) or 0
                ship = to_int(d.get("PreOrderShipDate"))
                if title_says_preorder(title) or MARKET_PRE_RE.search(title) or ship:
                    status = PRE
                else:
                    status = STOCK if qty > 0 else OUT
                img = d.get("Image") or ""
                it = Item("ruten", d["ProdId"], title, f"https://www.ruten.com.tw/item/show?{d['ProdId']}",
                          to_int((d.get("PriceRange") or [None])[0]), status, "", ruten_image(img))
                it.stock, it.verified = qty, True
                if ship and ship < 1000:
                    it.note = f"下單後約 {ship} 天出貨"
                out.append(it)
        return out


def ruten_image(path: str) -> str:
    """露天圖片分兩個主機：/c… 在 a.rimg.com.tw，/g… 在 gcs.rimg.com.tw（放錯會回傳佔位圖）。"""
    if not path:
        return ""
    host = "a.rimg.com.tw" if path.startswith("/c") else "gcs.rimg.com.tw"
    return f"https://{host}{path}"


# ======================================================================= Yahoo 拍賣
class Yahoo(Source):
    key = "yahoo"
    marketplace = True

    def search(self, q):
        r = self.get(f"https://tw.bid.yahoo.com/search/auction/product?p={quote(q)}&sort=-ptime")
        t = r.text
        i = t.find('"hits"')
        if i < 0:
            return []
        try:
            hits, _ = json.JSONDecoder().raw_decode(t[t.find("[", i):])
        except ValueError:
            return []
        out = []
        for h in hits[: self.limit]:
            title = clean(h.get("ec_title"))
            stock_ok = str(h.get("ec_stock_status", "1")) != "0"
            if title_says_preorder(title) or MARKET_PRE_RE.search(title):
                status = PRE
            else:
                status = STOCK if stock_ok else OUT
            pid = str(h.get("ec_productid"))
            it = Item("yahoo", pid, title, h.get("ec_item_url") or f"https://tw.bid.yahoo.com/item/{pid}",
                      to_int(h.get("ec_buyprice") or h.get("ec_price")), status, "",
                      h.get("ec_img_uri") or h.get("ec_image") or "", seller=clean(h.get("ec_storename")))
            it.verified = True
            it.extra = " ".join(x.get("item", "") for x in h.get("ec_hashtags") or [])
            out.append(it)
        return out


SOURCES = {c.key: c for c in (Books, Eslite, PChome, GMusic, Candlelight, Ruten, Yahoo)}
