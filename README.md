# OST Radar

台灣通路的日本動畫、電玩原聲實體盤（黑膠、CD、卡帶）資訊與比價。

https://wei176899.github.io/ost-radar/

## 開發

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS / Linux：.venv/bin/pip
.venv/Scripts/python -m tracker
.venv/Scripts/python -m tracker.thumbs
python -m http.server 8000 --bind 127.0.0.1 --directory site
```

設定：`tracker/config.json`

部分通路不接受海外連線，雲端排程會沿用上次資料。可在台灣網路以 `local-refresh.bat` 補抓並推送。

## 授權與聲明

商品資料、圖片與相關權利屬原通路及權利人所有，本站內容僅供參考。
