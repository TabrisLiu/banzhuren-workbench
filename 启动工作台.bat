@echo off
chcp 437 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title BZGZT Workbench

rem ===== locate a Python that has the deps installed =====
set "PY="
set "DEP=import fastapi,uvicorn,openpyxl,docx,httpx,multipart"

set "C1=C:\Users\Tabris\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if exist "%C1%" "%C1%" -c "%DEP%" >nul 2>nul && set "PY=%C1%"
if defined PY goto launch
python3 -c "%DEP%" >nul 2>nul && set "PY=python3"
if defined PY goto launch
py -3 -c "%DEP%" >nul 2>nul && set "PY=py -3"
if defined PY goto launch
python -c "%DEP%" >nul 2>nul && set "PY=python"
if defined PY goto launch

echo [ERROR] No Python 3 with required packages found.
echo Run once in a terminal:
echo     python -m pip install fastapi uvicorn openpyxl python-docx httpx python-multipart
echo See README.md  /  yi kan README.txt
pause
exit /b 1

:launch
rem ===== if already running, just open browser =====
netstat -ano | findstr ":8790" | findstr "LISTENING" >nul 2>nul
if errorlevel 1 goto start
echo Service already running, opening browser...
start "" http://127.0.0.1:8790
ping -n 4 127.0.0.1 >nul
exit /b 0

:start
echo Interpreter: %PY%
echo Starting, browser will open at http://127.0.0.1:8790
echo Keep this window open to run the app; close it to stop.
echo ------------------------------------------------------------
rem wait until server port is really listening, then open browser (max 30s)
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8790);$c.Close();Start-Process 'http://127.0.0.1:8790';exit}catch{Start-Sleep -Milliseconds 500}}"
%PY% -m uvicorn app.server.main:app --host 127.0.0.1 --port 8790
echo ------------------------------------------------------------
echo Server exited. Restarting in 10s (close window to cancel).
timeout /t 10 /nobreak >nul
if errorlevel 1 exit /b 0
goto launch
