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

from .models import (OUT, PRE, STOCK, UNKNOWN, Item, clean, is_future, month_day, norm_barcode, norm_date,
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

    timeout = 20                # 每個請求的逾時秒數
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
                r = self.s.request(method, url, timeout=self.timeout, **kw)
                if r.status_code in (429, 502, 503) and attempt < retries - 1:
                    time.sleep(6)
                    last = r
                    continue
                r.raise_for_status()
                if "maintenance" in r.url:  # 平台維護頁（例如 WACA 的 maintenance.waca.ec）
                    self.down = "網站維護中"
                    raise SourceDown(self.down)
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
        """發行日期取自商品頁（有快取）；購物車區塊有防機器人驗證，不做庫存查詢。"""
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
            it.barcode = norm_barcode(f.get("ean"))
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
            it.barcode = norm_barcode(d.get("ean")) or it.barcode
            if "預購" in str(mode) or (is_future(it.release) and btn == "add_to_shopping_cart"):
                it.status = PRE
                it.deadline = norm_date(d.get("sale_mode_end_date") or "")
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
                it.sold = to_int(p.get("total_sold")) or None
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
                it.sold = to_int(d.get("SoldQty")) or None
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
            it.sold = to_int(h.get("ec_buy_count")) or None
            it.extra = " ".join(x.get("item", "") for x in h.get("ec_hashtags") or [])
            out.append(it)
        return out


# ======================================================================= 山海山唱片行
SHS_KINDS = {"189": "vinyl", "187": "vinyl", "53": "vinyl", "58": "cd"}  # 動畫卡通、日韓影視、黑膠原聲、CD 原聲


class Shs(Source):
    key = "shs"
    catalog = True

    def crawl(self):
        out: dict[str, Item] = {}
        for kind, hint in SHS_KINDS.items():
            for page in range(1, 30):
                try:
                    r = self.get(f"https://www.shsmusic.tw/tw/product/index.php?kind={kind}&page={page}")
                except Exception as e:  # noqa: BLE001
                    self.log(f"  [山海山] 分類 {kind} 第 {page} 頁失敗: {e}")
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select(".pro-list .item[data-num]")
                fresh = [c for c in cards if c["data-num"] not in out]
                if not fresh:
                    break
                for c in fresh:
                    pid = c["data-num"]
                    tw = clean(c.select_one(".txt-tw").get_text()) if c.select_one(".txt-tw") else ""
                    en = clean(c.select_one(".txt-en").get_text()) if c.select_one(".txt-en") else ""
                    artist = clean(c.select_one(".author .txt-tw").get_text()) if c.select_one(".author .txt-tw") else ""
                    mark = clean(c.select_one(".CDmark").get_text()) if c.select_one(".CDmark") else ""
                    price = c.select_one(".price b")
                    img = c.select_one("a.pic img")
                    src = img.get("src", "") if img else ""
                    m = re.search(r"path=([^&]+)", src)
                    title = " ".join(x for x in (mark, tw, en) if x)
                    it = Item("shs", pid, title, f"https://www.shsmusic.tw/tw/product/show.php?num={pid}",
                              to_int(price.get_text()) if price else None, UNKNOWN,
                              image=(f"https://www.shsmusic.tw/module/smallimg3.php?path={m.group(1)}&w=600&h=600"
                                     if m else ""), seller=artist)
                    it.fmt_hint = "7inch" if "7" in mark else ("cd" if "CD" in mark.upper() else hint)
                    it.is_ost = True
                    it.extra = "動畫" if kind == "189" else ""
                    out[pid] = it
        return list(out.values())

    def verify(self, items, state, limit):
        n = 0
        for it in items[:limit]:
            try:
                txt = BeautifulSoup(self.get(it.url).text, "html.parser").get_text(" ", strip=True)
            except SourceDown:
                break
            except Exception as e:  # noqa: BLE001
                self.log(f"  [山海山] 複查失敗 {it.pid}: {e}")
                continue
            n += 1
            it.verified = True
            m = re.search(r"發行日期\s*(\d{4}-\d{2}-\d{2})", txt)
            if m:
                it.release = norm_date(m.group(1))
            m = re.search(r"國際條碼\s*(\d{8,14})", txt)
            if m:
                it.barcode = norm_barcode(m.group(1))
            m = re.search(r"商品狀態\s*(有現貨|需調貨|需預購|已售完|絕版)", txt)
            state_txt = m.group(1) if m else ""
            if state_txt == "有現貨":
                it.status = STOCK
            elif is_future(it.release):
                it.status = PRE
            elif state_txt == "需預購":  # 已發行但需向海外訂購，不算預購
                it.status, it.note = UNKNOWN, "可下單（海外調貨約一個月）"
            elif state_txt == "需調貨":
                it.status, it.note = UNKNOWN, "可下單（需調貨）"
            elif state_txt in ("已售完", "絕版"):
                it.status = OUT
        self.log(f"  [山海山] 已複查 {n} 筆")


# ======================================================================= 買動漫
class MyAcg(Source):
    key = "myacg"
    marketplace = True
    generic_only = True  # 站內搜尋每次約 30 秒，只跑一般關鍵字
    timeout = 45

    def search(self, q):
        r = self.get(f"https://www.myacg.com.tw/goods_list_show_005.php?keyword_body={quote(q)}",
                     headers={"Referer": "https://www.myacg.com.tw/goods_list.php"})
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for li in soup.select("#Goods_list_block > li[title]")[: self.limit]:
            a = li.select_one('a[href*="goods_detail.php?gid="]')
            if not a:
                continue
            gid = re.search(r"gid=(\d+)", a["href"]).group(1)
            title = clean(li.get("title"))
            price = li.select_one(".t_price")
            img = li.select_one(".pic img")
            sold_out = "已售完" in li.get_text() or "補貨中" in li.get_text()
            if title_says_preorder(title) or MARKET_PRE_RE.search(title):
                status = PRE
            else:
                status = OUT if sold_out else STOCK
            it = Item("myacg", gid, title, f"https://www.myacg.com.tw/goods_detail.php?gid={gid}",
                      to_int(price.get_text()) if price else None, status, "", img.get("src", "") if img else "")
            it.verified = True  # 列表即賣場即時狀態
            m = re.search(r"銷量[:：]\s*(\d+)", li.get_text(" ", strip=True))
            it.sold = int(m.group(1)) if m and int(m.group(1)) > 0 else None
            out.append(it)
        return out


# ======================================================================= 佳佳唱片行
CCR_LISTS = [("PreGoods.php", "4"), ("PreGoods.php", "LP"), ("release.php", "4"), ("release.php", "LP")]  # 日文 / 黑膠


class Ccr(Source):
    key = "ccr"
    catalog = True

    def crawl(self):
        out: dict[str, Item] = {}
        for page, s in CCR_LISTS:
            try:
                r = self.get(f"https://www.ccr.com.tw/{page}?S={s}")
            except Exception as e:  # noqa: BLE001
                self.log(f"  [佳佳] {page}?S={s} 失敗: {e}")
                continue
            for tb in BeautifulSoup(r.text, "html.parser").select("tbody.item_row[data-id]"):
                pid = tb["data-id"]
                if pid in out:
                    continue
                art = tb.select_one(".item_artist")
                ttl = tb.select_one(".item_article")
                spec = clean(tb.select_one(".item_spec").get_text()) if tb.select_one(".item_spec") else ""
                place = clean(tb.select_one(".item_place").get_text()) if tb.select_one(".item_place") else ""
                pub = clean(tb.select_one(".item_publish").get_text()) if tb.select_one(".item_publish") else ""
                title = clean(ttl.get("title") or ttl.get_text()) if ttl else ""
                artist = clean(art.get_text()) if art else ""
                it = Item("ccr", pid, f"{artist} {title} {spec}".strip(), f"https://www.ccr.com.tw/goods/{pid}",
                          None, PRE if page == "PreGoods.php" else UNKNOWN, norm_date(pub), seller=artist)
                it.fmt_hint = "vinyl" if s == "LP" or "LP" in spec.upper() else ("cd" if "CD" in spec.upper() else None)
                it.note = place
                out[pid] = it
        return list(out.values())

    def verify(self, items, state, limit):
        n = 0
        for it in items[:limit]:
            try:
                t = self.get(it.url).text
            except SourceDown:
                break
            except Exception as e:  # noqa: BLE001
                self.log(f"  [佳佳] 複查失敗 {it.pid}: {e}")
                continue
            n += 1
            it.verified = True
            txt = BeautifulSoup(t, "html.parser").get_text(" ", strip=True)
            m = re.search(r"產品條碼\s*:\s*(\w+)", txt)
            if m:
                it.barcode = norm_barcode(m.group(1))
            m = re.search(r"網路價\s*NT\$\s*:\s*([\d,]+)", txt)
            if m:
                it.price = to_int(m.group(1))
            m = re.search(r'og:image" content="([^"]+)"', t)
            if m:
                it.image = m.group(1)
            m = re.search(r"發行日期\s*:\s*([\d/]+)", txt)
            if m:
                it.release = norm_date(m.group(1)) or it.release
            if "無庫存" in txt or "已售完" in txt:
                it.status = OUT
            elif "預購商品" in txt or is_future(it.release):
                it.status = PRE
            elif "放入購物車" in txt:
                it.status = STOCK
            if "庫存少量" in txt:
                it.note = (it.note + "・庫存少量").strip("・")
        self.log(f"  [佳佳] 已複查 {n} 筆")


# ======================================================================= 小白兔唱片
WWR_RE = re.compile(r'"name":"((?:[^"\\]|\\.)*)","type":"album","price":(\d+),"vipPrice":\d+,"stockQuantity":(-?\d+)'
                    r'.*?"slug":"([^"]+)","images":\[("[^"]*")?')


class Wwr(Source):
    key = "wwr"
    bare_franchise = True

    def search(self, q):
        t = self.get(f"https://wwr.com.tw/search?q={quote(q)}").text
        t = t.replace('\\"', '"')
        out, seen = [], set()
        for name, price, qty, slug, img in WWR_RE.findall(t):
            if slug in seen:
                continue
            seen.add(slug)
            try:
                name = json.loads(f'"{name}"')
            except ValueError:
                pass
            qty = int(qty)
            title = clean(name)
            status = PRE if title_says_preorder(title) else (STOCK if qty > 0 else OUT)
            it = Item("wwr", slug, title, f"https://wwr.com.tw/albums/{slug}", int(price), status,
                      image=f"https://fs.wwr.com.tw/img/{img.strip(chr(34))}" if img else "")
            it.stock, it.verified = max(qty, 0), True
            it.fmt_hint = "vinyl" if "[Vinyl]" in title else ("cd" if "[CD]" in title else None)
            out.append(it)
            if len(out) >= self.limit * 2:
                break
        return out


# ======================================================================= 五大唱片
class FiveMusic(Source):
    key = "fivemusic"
    bare_franchise = True

    def search(self, q):
        r = self.post("https://www.5music.com.tw/search.asp", data={"sclass": "1", "stxt": q},
                      headers={"Referer": "https://www.5music.com.tw/product_cat11.asp"})
        r.encoding = "utf-8"
        out = []
        for box in BeautifulSoup(r.text, "html.parser").select(".record-box")[: self.limit]:
            a = box.select_one('a[href*="cdno="]')
            if not a:
                continue
            cdno = re.search(r"cdno=(\d+)", a["href"]).group(1)
            artist = clean(box.select_one("h4").get_text()) if box.select_one("h4") else ""
            title = clean(box.select_one(".des").get_text()) if box.select_one(".des") else ""
            img = box.select_one("img")
            src = (img.get("data-src") or img.get("src") or "") if img else ""
            m = re.search(r"預購至\s*([\d/]+)", title)
            it = Item("fivemusic", cdno, f"{artist} {title}".strip(), f"https://www.5music.com.tw/CDList-C.asp?cdno={cdno}",
                      None, PRE if m or title_says_preorder(title) else UNKNOWN,
                      image=f"https://www.5music.com.tw/{src.lstrip('/')}" if src else "", seller=artist)
            it.fmt_hint = "cd"  # 五大的品名通常只有黑膠會註明格式
            if m:
                it.deadline = month_day(m.group(1))
            out.append(it)
        return out

    def verify(self, items, state, limit):
        n = 0
        for it in items[:limit]:
            try:
                r = self.get(it.url)
            except SourceDown:
                break
            except Exception as e:  # noqa: BLE001
                self.log(f"  [五大] 複查失敗 {it.pid}: {e}")
                continue
            r.encoding = "utf-8"
            txt = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
            n += 1
            it.verified = True
            m = re.search(r"發行日期\s*([\d/]+)", txt)
            if m:
                it.release = norm_date(m.group(1))
            m = re.search(r"條碼\s*(\d{8,14})", txt)
            if m:
                it.barcode = norm_barcode(m.group(1))
            if re.search(r"音樂類型\s*黑膠", txt):
                it.fmt_hint = "vinyl"
            if "目前無現貨" in txt:
                it.status = PRE if is_future(it.release) else OUT
            elif "目前有現貨" in txt or "現貨供應" in txt:
                it.status = STOCK
            elif is_future(it.release):
                it.status = PRE
        self.log(f"  [五大] 已複查 {n} 筆")


# ======================================================================= 爛調唱片（Shopify）
class RottenBlues(Source):
    key = "rottenblues"
    catalog = True
    host = "https://www.rottenblues.com"

    def crawl(self):
        out = []
        for page in range(1, 60):
            prods = self.get(f"{self.host}/products.json?limit=250&page={page}").json().get("products", [])
            if not prods:
                break
            for p in prods:
                tags = p.get("tags") or []
                ptype = p.get("product_type") or ""
                title = clean(p.get("title"))
                variants = p.get("variants") or [{}]
                available = any(v.get("available") for v in variants)
                pre = any("預購" in t or "Pre-order" in t for t in tags) or title_says_preorder(title)
                status = (PRE if available else OUT) if pre else (STOCK if available else OUT)
                img = (p.get("images") or [{}])[0].get("src", "") if p.get("images") else ""
                it = Item("rottenblues", str(p["id"]), title, f"{self.host}/products/{quote(p.get('handle', ''))}",
                          to_int(variants[0].get("price")), status, image=img, seller=clean(p.get("vendor")))
                it.verified = True  # 商品資料即時含是否可購買
                it.extra = f"{ptype} {' '.join(tags)}"
                it.is_ost = any("Soundtrack" in t or "Anime" in t for t in tags)
                it.fmt_hint = ("vinyl" if re.search(r"黑膠|Vinyl|LP", ptype, re.I)
                               else "cassette" if re.search(r"卡帶|Cassette", ptype, re.I)
                               else "cd" if "CD" in ptype.upper() else None)
                out.append(it)
        return out


# ======================================================================= THT 唱片（EasyStore）
THT_COLLECTIONS = ["o-s-t-v-a", "japanese"]


class Tht(Source):
    key = "tht"
    catalog = True
    host = "https://www.thtrecords.com"

    def crawl(self):
        out: dict[str, Item] = {}
        for col in THT_COLLECTIONS:
            for page in range(1, 40):
                try:
                    r = self.get(f"{self.host}/collections/{col}?page={page}")
                except SourceDown:
                    return list(out.values())
                except Exception as e:  # noqa: BLE001
                    self.log(f"  [THT] {col} 第 {page} 頁失敗: {e}")
                    break
                cards = BeautifulSoup(r.text, "html.parser").select("#main-collection-product-grid > li")
                fresh = 0
                for li in cards:
                    badge = li.select_one("[data-product-id]")
                    a = li.select_one('a[href*="/products/"]')
                    if not badge or not a:
                        continue
                    pid = badge["data-product-id"]
                    if pid in out:
                        continue
                    fresh += 1
                    title = clean(li.select_one(".card__heading, h3").get_text()) if li.select_one(".card__heading, h3")                         else clean(a.get_text())
                    title = re.sub(r"\s*(Regular price|Sale price|Unit price).*$", "", title)
                    title = re.sub(r"^(售完|Sold out)\s*", "", title, flags=re.I).strip()
                    img = li.select_one("img")
                    src = (img.get("src") or img.get("data-src") or "") if img else ""
                    available = badge.get("data-product-available") == "1"
                    m = re.search(r"(\d{4}/\d{1,2}(?:/\d{1,2})?)\s*發行", title)
                    release = norm_date(m.group(1)) if m and m.group(1).count("/") == 2 else (
                        f"{m.group(1).split('/')[0]}-{int(m.group(1).split('/')[1]):02d}" if m else "")
                    if not release:
                        m2 = re.search(r"(\d{1,2}/\d{1,2})\s*發行", title)
                        release = month_day(m2.group(1)) if m2 else ""
                    pre = bool(re.search(r"預訂|預購", title))
                    status = (PRE if pre else STOCK) if available else OUT
                    href = a["href"].split("?")[0]
                    product_path = "/products/" + href.split("/products/", 1)[1]
                    it = Item("tht", pid, title, f"{self.host}{product_path}",
                              to_int(badge.get("data-product-price")), status, release,
                              src.split("?")[0] + "?width=600" if src else "")
                    it.verified = True  # 列表即含可否購買
                    it.is_ost = col == "o-s-t-v-a"
                    it.extra = "日本" if col == "japanese" else ""
                    out[pid] = it
                if not fresh:
                    break
        return list(out.values())


SOURCES = {c.key: c for c in (Books, Eslite, PChome, GMusic, Candlelight, Shs, Ccr, Wwr, FiveMusic,
                              RottenBlues, Tht, Ruten, Yahoo, MyAcg)}
