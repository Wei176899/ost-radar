# OST Radar

日本動畫與電玩原聲實體盤（黑膠、CD、卡帶）在台灣通路的預購與現貨資訊。

**https://wei176899.github.io/ost-radar/**

## 概覽

資料由排程定期自台灣各電商、唱片行與拍賣平台取得，經分類後發布為靜態網站。
商品狀態以各通路的庫存資訊或商品頁為準，並附上相關的發售消息。

收錄通路：博客來、誠品線上、PChome 24h、玫瑰大眾、燭光唱片、山海山唱片行、佳佳唱片行、
小白兔唱片、五大唱片、露天拍賣、Yahoo 拍賣、買動漫。版本資料另可連結至 Discogs 查詢。

## 架構

```
tracker/    資料擷取、分類與發售消息
site/       靜態網站（HTML / CSS / JavaScript）
data/       歷史狀態
.github/    排程與部署
```

## 本機開發

```bash
pip install -r requirements.txt
python -m tracker
python -m tracker.thumbs
python -m http.server 8000 --bind 127.0.0.1 --directory site
```

追蹤的作品、通路與關鍵字設定於 `tracker/config.json`。

## 部署

推送至 `main` 後由 GitHub Actions 建置並發布至 GitHub Pages；資料更新亦由同一流程定期執行。

## 說明

- 本站資料僅供參考，價格、庫存與發售日期請以各通路頁面為準。
- 商品名稱、圖片及相關權利屬於各通路與權利人所有。
