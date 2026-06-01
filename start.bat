@echo off
REM VoltaNode startup script — opens 4 terminals: backend, frontend, monitor, collector.
REM Each runs in its own window so you can Ctrl-C any of them individually.
REM
REM Run from D:\VoltaNode\ by double-clicking, or from a normal cmd window.

set ROOT=%~dp0
if %ROOT:~-1%==\ set ROOT=%ROOT:~0,-1%

echo Starting VoltaNode services from %ROOT%
echo.

REM Clear stale listeners so restarts don't stack duplicate processes
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3001 " ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1

REM Backend (FastAPI on :8000) — runs from trading-bot-backend/
start "VoltaNode Backend" cmd /k "cd /d %ROOT%\trading-bot-backend && python run.py --mode api --host 127.0.0.1 --port 8000"

REM Wait a couple seconds so backend port is open before frontend proxies start hitting it
timeout /t 3 /nobreak >nul

REM Frontend (Vite on :3001 per app/vite.config.ts) — runs from app/
start "VoltaNode Frontend" cmd /k "cd /d %ROOT%\app && npm run dev"

REM Wait for frontend
timeout /t 3 /nobreak >nul

REM Bot monitor — polls /orders/ every 30s, emits a line per new fill / status change
start "VoltaNode Monitor" cmd /k "python -u %ROOT%\.claude\bot_monitor.py"

REM Wait a bit longer so the collector's initial backend probe succeeds
timeout /t 4 /nobreak >nul

REM Data collector — pulls news sentiment / squeeze / macro / advisor on a schedule.
REM Writes JSONL files to data/collector/ for historical analysis & backtest replay.
start "VoltaNode Collector" cmd /k "python -u %ROOT%\scripts\collector.py"

echo.
echo All four services launched in separate windows.
echo  - Backend:   http://127.0.0.1:8000
echo  - Frontend:  http://localhost:3001
echo  - Monitor:   prints fills + heartbeats; Ctrl-C in its window to stop
echo  - Collector: writes data/collector/*.jsonl on schedule; Ctrl-C to stop
echo.
echo Close this window or press any key to dismiss.
pause >nul
