@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
python -m tracker %*
python -m tracker.thumbs
start "" http://localhost:8000
python -m http.server 8000 --bind 127.0.0.1 --directory site
