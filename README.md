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

## 授權與聲明

商品資料、圖片與相關權利屬原通路及權利人所有，本站內容僅供參考。
