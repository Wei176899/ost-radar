@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
.venv\Scripts\python -m tracker %*
.venv\Scripts\python -m tracker.thumbs
start "" http://localhost:8000
.venv\Scripts\python -m http.server 8000 --bind 127.0.0.1 --directory site
