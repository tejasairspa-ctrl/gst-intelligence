@echo off
REM ============================================================
REM  GST Intelligence - one-click launcher
REM  Starts backend (Flask :8000) + frontend (Vite :3000)
REM  and opens the app in your browser.
REM ============================================================

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

echo Starting GST Intelligence...
echo   Backend : %BACKEND%
echo   Frontend: %FRONTEND%
echo.

REM --- Backend (uses project venv) -------------------------------------------
if exist "%BACKEND%\venv\Scripts\python.exe" (
    start "GST Backend" cmd /k "cd /d "%BACKEND%" && venv\Scripts\python.exe main.py"
) else (
    start "GST Backend" cmd /k "cd /d "%BACKEND%" && python main.py"
)

REM --- Frontend (Vite dev server on port 3000) -------------------------------
start "GST Frontend" cmd /k "cd /d "%FRONTEND%" && npm run dev"

REM --- Give the servers a few seconds, then open the browser -----------------
timeout /t 6 /nobreak >nul
start "" "http://localhost:3000"

echo.
echo Two windows opened (GST Backend, GST Frontend).
echo Closing THIS window will NOT stop them.
echo To stop the app, close those two windows.
timeout /t 4 /nobreak >nul
