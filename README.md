# 原聲雷達 OST Radar

追蹤台灣 7 個通路的**日本動畫／電玩原聲實體盤**（黑膠 LP、7 吋、CD、卡帶），
標示預購／現貨／缺貨，逐筆回到商品頁或庫存 API 複查，並收集發售新聞。
GitHub Actions 每 3 天自動執行一次，結果發布成 GitHub Pages 網站（手機、電腦都能看）。

## 結構

```
tracker/            爬蟲（python -m tracker）
  config.json       關鍵字、追蹤作品、通路開關、新聞來源
  sources.py        7 個通路：搜尋 + 庫存複查
  classify.py       格式／類型／版本／作品／日系判斷
  news.py           Google News + 海外遊戲動畫唱片廠牌新品
  thumbs.py         封面縮圖（WebP 360px＋主色），部署時產生、以快取保存
site/               網站（純 HTML/CSS/JS，無需建置）
  data/             爬蟲輸出：items.json、news.json、meta.json、items.csv
data/state.json     歷史紀錄（判斷新上架、補貨、到貨、降價）
.github/workflows/update.yml   每 3 天排程 + 部署
```

## 通路與庫存複查

| 通路 | 方式 | 複查 |
|---|---|---|
| 誠品線上 | 搜尋 API | 商品 API（庫存數、按鈕狀態、出版日） |
| 玫瑰大眾 | 搜尋 API | 即時庫存數（搜尋結果即含） |
| 燭光唱片 | 原聲帶／J-Pop／預購分類頁 | 商品頁（已售完、預計出貨月份） |
| PChome 24h | 搜尋 API | 按鈕 API（ForSale / SoldOut、數量） |
| 露天拍賣 | 搜尋 + 商品 API | 賣家庫存數、預購出貨天數 |
| Yahoo 拍賣 | 搜尋頁資料 | 賣家庫存狀態 |
| 博客來 | 搜尋頁 + 商品頁發行日 | 購物車區塊有防機器人驗證，**不複查**，顯示「可訂購（未複查）」 |

## 本機執行

```
pip install -r requirements.txt
python -m tracker                # 完整（約 30 分鐘）
python -m tracker --quick        # 只跑一般關鍵字
python -m tracker --only eslite,candlelight --no-news
python -m tracker.thumbs         # 產生封面縮圖（site/img/，不進 git）
python -m http.server 8000 --bind 127.0.0.1 --directory site   # 開 http://localhost:8000 預覽
```

## 部署到 GitHub（免費）

1. 在 GitHub 建立**公開** repository，把整個資料夾推上去（`main` 分支）。
2. Settings → Pages → Source 選 **GitHub Actions**。
3. Actions → 「更新資料並部署網站」→ Run workflow 先手動跑一次。
4. 之後每 3 天台北時間早上 6 點自動更新；修改 `site/` 也會自動重新部署。

## 自訂

- 追新作品：在 `tracker/config.json` 的 `franchises` 加一筆（`aliases` 第一個用來搜尋）。
- 關掉某通路：`sources` 裡改成 `false`。
- 新聞關鍵字、海外廠牌：`news` 區塊。

## 限制

- 各通路改版時解析可能失效；失敗次數會顯示在網站「追蹤通路」區。
- GitHub Actions 主機在海外，少數台灣網站可能對海外連線較嚴格，若某通路長期 0 筆可改在本機排程執行後推送。
- 「日系」「動畫／遊戲」為關鍵字規則判斷，少數作品可能誤判。
