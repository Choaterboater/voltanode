@echo off
REM VoltaNode startup script — opens 3 terminals: backend, frontend, monitor.
REM Each runs in its own window so you can Ctrl-C any of them individually.
REM
REM Run from D:\VoltaNode\ by double-clicking, or from a normal cmd window.

set ROOT=%~dp0
if %ROOT:~-1%==\ set ROOT=%ROOT:~0,-1%

echo Starting VoltaNode services from %ROOT%
echo.

REM Backend (FastAPI on :8000) — runs from trading-bot-backend/
start "VoltaNode Backend" cmd /k "cd /d %ROOT%\trading-bot-backend && python run.py --mode api --host 127.0.0.1 --port 8000"

REM Wait a couple seconds so backend port is open before frontend proxies start hitting it
timeout /t 3 /nobreak >nul

REM Frontend (Vite — auto-falls-back to :3001 if :3000 is busy) — runs from app/
start "VoltaNode Frontend" cmd /k "cd /d %ROOT%\app && npm run dev"

REM Wait for frontend
timeout /t 3 /nobreak >nul

REM Bot monitor — polls /orders/ every 30s, emits a line per new fill / status change
start "VoltaNode Monitor" cmd /k "python -u %ROOT%\.claude\bot_monitor.py"

echo.
echo All three services launched in separate windows.
echo  - Backend:  http://127.0.0.1:8000
echo  - Frontend: http://localhost:3000  (or :3001 if :3000 was busy)
echo  - Monitor:  prints fills + heartbeats; Ctrl-C in its window to stop
echo.
echo Close this window or press any key to dismiss.
pause >nul
