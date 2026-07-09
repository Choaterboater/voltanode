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

REM Wait until :8000 is actually free (taskkill is async; avoids bind race)
set /a _wait=0
:wait_8000
netstat -ano | findstr ":8000 " | findstr LISTENING >nul 2>&1
if errorlevel 1 goto port_free
set /a _wait+=1
if %_wait% GEQ 20 (
  echo WARNING: port 8000 still in use after kill attempts — starting anyway
  goto port_free
)
REM ping-based sleep works when stdin is redirected (timeout.exe does not)
ping -n 2 127.0.0.1 >nul
goto wait_8000

:port_free
REM Backend (FastAPI on :8000) — runs from trading-bot-backend/
start "VoltaNode Backend" cmd /k "cd /d %ROOT%\trading-bot-backend && python run.py --mode api --host 127.0.0.1 --port 8000"

REM Wait for backend to bind before frontend / monitor hit it
ping -n 5 127.0.0.1 >nul

REM Frontend (Vite on :3001 per app/vite.config.ts) — runs from app/
start "VoltaNode Frontend" cmd /k "cd /d %ROOT%\app && npm run dev"

ping -n 4 127.0.0.1 >nul

REM Bot monitor — polls /orders/ every 30s, emits a line per new fill / status change
start "VoltaNode Monitor" cmd /k "python -u %ROOT%\.claude\bot_monitor.py"

ping -n 5 127.0.0.1 >nul

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
if /i "%1"=="--no-pause" goto :eof
echo Close this window or press any key to dismiss.
pause >nul
