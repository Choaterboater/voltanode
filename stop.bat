@echo off
REM Stop all VoltaNode services in one shot.
REM Kills python processes serving on 8000 + node processes for vite + the monitor.

echo Stopping VoltaNode services...

REM Kill anything bound to :8000 (backend uvicorn)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
  echo   killing pid %%p (backend on :8000)
  taskkill /F /PID %%p >nul 2>&1
)

REM Kill anything bound to :3000 / :3001 (frontend vite)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000 " ^| findstr LISTENING') do (
  echo   killing pid %%p (frontend on :3000)
  taskkill /F /PID %%p >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3001 " ^| findstr LISTENING') do (
  echo   killing pid %%p (frontend on :3001)
  taskkill /F /PID %%p >nul 2>&1
)

REM Kill the monitor python process by command-line match
wmic process where "commandline like '%%bot_monitor.py%%'" delete >nul 2>&1

echo Done.
pause
