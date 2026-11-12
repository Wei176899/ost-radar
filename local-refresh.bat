@echo off
rem 補抓雲端（海外 IP）連不上的通路，合併到最新資料後推送；推送後 GitHub Actions 會自動重新部署網站。
rem 建議在雲端每日更新（06:17）之後執行，例如以工作排程器每天 07:30 執行一次。
chcp 65001 >nul
cd /d "%~dp0"
set LOG=data\local-refresh.log
echo ==== %date% %time% > %LOG%

git pull -q --rebase -X theirs origin main >> %LOG% 2>&1 || goto fail
.venv\Scripts\python -m tracker --only books,candlelight,myacg --merge --no-news >> %LOG% 2>&1 || goto fail
.venv\Scripts\python -c "import json; [json.load(open(f, encoding='utf-8')) for f in ('site/data/items.json', 'site/data/meta.json', 'data/state.json')]" >> %LOG% 2>&1 || goto fail

git add site/data data/state.json
git diff --cached --quiet && goto done
git commit -q -m "chore(data): local refresh %date:~0,10%" >> %LOG% 2>&1 || goto fail
for /l %%i in (1,1,3) do (
  git pull -q --rebase -X theirs origin main >> %LOG% 2>&1 && git push -q origin HEAD:main >> %LOG% 2>&1 && goto done
  git rebase --abort >nul 2>&1
  timeout /t 15 /nobreak >nul
)
goto fail

:done
echo OK >> %LOG%
exit /b 0

:fail
echo FAILED >> %LOG%
exit /b 1
